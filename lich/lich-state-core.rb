# frozen_string_literal: true

require 'json'
require 'thread'
require 'time'

# Frontend-independent projection of explicit Lich state. Consumers choose the
# projections they need; this module performs no I/O, emits no frontend markup,
# sends no game commands, and never derives durable truth from Story.
module LichState
  MAX_DECODED_BYTES = 65_536
  MAX_ITEMS = 512
  MAX_ANCESTRY = 16
  MAX_RECENT_LOOT = 100
  ITEM_KINDS = %w[item container scroll jewelry weapon armor consumable currency other].freeze
  PROJECTION_TYPES = %i[
    session inventory bounty society recent_loot combat experience
    known_spells cooldowns
  ].freeze
  STAT_CODES = {
    'strength' => 'STR', 'constitution' => 'CON', 'dexterity' => 'DEX',
    'agility' => 'AGI', 'discipline' => 'DIS', 'aura' => 'AUR',
    'logic' => 'LOG', 'intuition' => 'INT', 'wisdom' => 'WIS', 'influence' => 'INF'
  }.freeze

  ExtractedState = Struct.new(:identity_token, :projections, :hub, keyword_init: true)

  # Adapter from Lich's explicit in-memory state to protocol payloads. Missing
  # methods and unknown values are omitted instead of guessed.
  class LichSource
    def initialize(
      xml_data: nil,
      game_obj: nil,
      spells: nil,
      active_spells: nil,
      cooldowns: nil,
      stats: nil,
      infomon: nil,
      map: nil,
      clock: Time
    )
      @xml_data = xml_data || constant(:XMLData)
      @game_obj = game_obj || constant(:GameObj)
      @spells = spells || constant(:Spells)
      @active_spells = active_spells || constant(:Spell)
      @cooldowns = cooldowns || nested_constant(:Lich, :Gemstone, :Effects, :Cooldowns)
      @stats = stats
      @infomon = infomon
      @map = map || constant(:Map)
      @clock = clock
      @recent_loot = []
      @identity_token = nil
      @identity_mutex = Mutex.new
      @read_mutex = Mutex.new
      @read_cache = nil
      @character_observations = {}
      @character_capture = nil
      @character_revision = Hash.new(0)
      @character_cache_identity = nil
    end

    # Capture one coherent live read and project it to both consumers. A
    # consumer chooses which slower projections are due; the compact hub
    # projection is always built from the same memoized XMLData/GameObj read.
    def extract(projection_types: PROJECTION_TYPES, hub_context: nil)
      selected = Array(projection_types).map(&:to_sym)
      unknown = selected - PROJECTION_TYPES
      raise ArgumentError, "unknown state projection(s): #{unknown.join(', ')}" unless unknown.empty?

      @read_mutex.synchronize do
        @read_cache = {}
        starting_identity = identity_token
        session_payload = session
        combat_payload = combat
        projections = selected.to_h do |type|
          payload = case type
                    when :session then session_payload
                    when :combat then combat_payload
                    else public_send(type)
                    end
          [type, payload]
        end
        hub = hub_context ? hub_snapshot(hub_context, session_payload, combat_payload) : nil
        ending_identity = @identity_mutex.synchronize do
          synchronize_identity_locked(observed_identity(use_cache: false))
        end
        return nil unless ending_identity == starting_identity

        ExtractedState.new(
          identity_token: starting_identity,
          projections: projections,
          hub: hub
        )
      ensure
        @read_cache = nil
      end
    end

    def ready?
      !identity_token.nil?
    end

    # Infomon has already parsed this server chunk before downstream hooks run
    # (Lich games.rb process_xml_data -> process_downstream_hooks). Preserve a
    # completion timestamp even when the same values cause Infomon's DB write
    # to be a no-op. An unrelated prompt alone is never a completed inspection.
    def observe_character_data(server_string, lines)
      @identity_mutex.synchronize do
        observed = observed_identity(use_cache: false)
        return unless synchronize_identity_locked(observed)

        character = observed.fetch(:character)
        Array(lines).each do |raw_line|
          line = raw_line.to_s.strip
          if (header = line.match(/\AName:\s+(.+?)\s+Race:\s+(.+?)\s+Profession:\s+([^()]+)(?:\s+\(|\z)/))
            @character_capture = nil
            if header[1].split.first.to_s.casecmp?(character)
              @character_capture = {
                category: :info, terminal: false,
                values: { race: header[2].strip, profession: header[3].strip, stats: {} }
              }
            end
          elsif (header = line.match(/\A(\w+) \(at level (\d+)\), your current skill bonuses and ranks/))
            @character_capture = nil
            if header[1].casecmp?(character)
              @character_capture = {
                category: :skills, level: header[2].to_i, terminal: false, spell_lists: false,
                values: { skills: {}, spell_circles: {}, training_points: {} }
              }
            end
          elsif @character_capture
            capture_character_row(line)
          end
        end
        if server_string.to_s.match?(/<prompt(?:\s|>)/)
          capture = @character_capture
          if capture && capture[:terminal] && capture[:level]
            category = capture.fetch(:category)
            @character_observations[category] = {
              source: category.to_s, observed_at: @clock.now.utc.iso8601(6),
              observed_level: capture[:level], complete: true, values: capture.fetch(:values)
            }
            @character_revision[category] += 1
          end
          @character_capture = nil
        end
      end
    end

    def character_recon_revision(category)
      @identity_mutex.synchronize do
        synchronize_identity_locked(observed_identity(use_cache: false))
        @character_revision[category.to_sym]
      end
    end

    def character_data
      @identity_mutex.synchronize do
        return unless synchronize_identity_locked(observed_identity)

        level = integer_value(@xml_data, :level)
        cached = cached_character_data(level)
        %i[info skills].to_h do |category|
          observation = @character_observations[category]
          payload = if observation && observation[:observed_level] == level
                      { **observation, values: { **observation.fetch(:values) } }
                    else
                      { source: 'infomon_cache', observed_at: nil, observed_level: nil,
                        complete: false, values: cached.fetch(category) }
                    end
          payload[:values][:level] = level if category == :info && level
          [category, payload]
        end
      end
    end

    # Name, game instance and player ID are explicit XMLData identity fields.
    # Requiring all three keeps state publication closed while Lich is between
    # characters or still assembling a new session. Any identity boundary also
    # clears source-owned ephemeral state before another payload can observe it.
    def identity_token
      @identity_mutex.synchronize do
        synchronize_identity_locked(observed_identity)
      end
    end

    def session
      @identity_mutex.synchronize do
        observed = observed_identity
        token = synchronize_identity_locked(observed)
        if token
          payload = {
            active: true, identity: token,
            character: observed.fetch(:character), game: observed.fetch(:game)
          }
          # Stats/Infomon can load after this publisher is constructed in the
          # long-lived Lich runtime, so resolve the default lazily.
          stats = @stats || nested_constant(:Lich, :Gemstone, :Stats) || constant(:Stats)
          profession = clean_text(value(stats, :profession), 160)
          payload[:profession] = profession unless profession.empty?
          payload
        else
          { active: false }
        end
      end
    end

    def inventory
      return unless ready? && @game_obj

      roots = array_value(@game_obj, :inv)
      containers = hash_value(@game_obj, :containers)
      hands = [value(@game_obj, :right_hand), value(@game_obj, :left_hand)].compact
      objects = (roots + containers.values.flatten + hands).compact
      objects = objects.uniq { |item| item_id(item) }
      objects_by_id = objects.to_h { |item| [item_id(item), item] }.reject { |id, _item| id.empty? || id == '0' }
      parents = parent_index(containers)

      items = objects_by_id.filter_map do |id, item|
        inventory_item(item, id, parents, containers)
      end.sort_by { |item| [item.fetch(:ancestry).length, item.fetch(:id)] }.first(MAX_ITEMS)
      { items: items }
    end

    def bounty
      return unless ready? && @xml_data&.respond_to?(:bounty_task)

      content = clean_text(value(@xml_data, :bounty_task), 2_000)
      { task: content.empty? ? nil : { text: content } }
    end

    def society
      return unless ready? && @xml_data&.respond_to?(:society_task)

      content = clean_text(value(@xml_data, :society_task), 2_000)
      { tasks: content.empty? ? [] : [{ text: content }] }
    end

    def recent_loot
      @identity_mutex.synchronize do
        return unless synchronize_identity_locked(observed_identity)

        { items: @recent_loot.map(&:dup) }
      end
    end

    # Scripts with an attributable loot result may call this method. Room text
    # and GameObj.loot are deliberately not treated as acquisition evidence.
    def record_loot(objects, source:)
      starting_identity = identity_token
      return false unless starting_identity

      source_text = clean_text(source, 160)
      return false if source_text.empty?

      entries = Array(objects).filter_map do |item|
        id = item_id(item)
        noun = clean_text(value(item, :noun), 160)
        name = clean_text(value(item, :name), 1_000)
        next if id.empty? || id == '0' || noun.empty? || name.empty?

        { id: id, noun: noun, name: name, source: source_text, at: now }
      end
      return false if entries.empty?

      @identity_mutex.synchronize do
        return false unless synchronize_identity_locked(observed_identity) == starting_identity

        @recent_loot.concat(entries)
        @recent_loot = @recent_loot.last(MAX_RECENT_LOOT)

        # An item adapter may yield while its fields are read. Recheck after
        # building and appending; a switch here clears the just-appended data.
        synchronize_identity_locked(observed_identity) == starting_identity
      end
    end

    def combat
      return unless ready?

      target_id = clean_text(value(@xml_data, :current_target_id), 80)
      target_object = value(@game_obj, :target)
      target = target_id.empty? ? nil : { id: target_id }
      if target && target_object
        noun = clean_text(value(target_object, :noun), 160)
        name = clean_text(value(target_object, :name), 1_000)
        target[:noun] = noun unless noun.empty?
        target[:name] = name unless name.empty?
      end

      result = { target: target }
      stance = clean_text(value(@xml_data, :stance_text), 80)
      result[:stance] = stance unless stance.empty?
      result[:roundtime] = roundtime
      metadata = {}
      indicators = value(@xml_data, :indicator)
      if indicators.respond_to?(:to_h)
        indicator_hash = indicators.to_h
        metadata[:stunned] = indicator_hash['IconSTUNNED'] == 'y'
        metadata[:dead] = indicator_hash['IconDEAD'] == 'y'
      end
      encumbrance = numeric_value(@xml_data, :encumbrance_value)
      metadata[:encumbrance] = encumbrance if encumbrance && encumbrance >= 0
      result[:metadata] = metadata unless metadata.empty?
      result
    end

    def experience
      return unless ready?

      result = {}
      level = integer_value(@xml_data, :level)
      result[:level] = level if level && level >= 0

      next_level_text = clean_text(value(@xml_data, :next_level_text), 256)
      next_level_value = numeric_value(@xml_data, :next_level_value)
      unless next_level_text.empty? || !next_level_value
        progress = { value: next_level_value, max: 100, label: next_level_text }
        remaining = numeric_value(@xml_data, :until_next)
        progress[:remaining] = remaining if remaining && remaining >= 0
        result[:progress] = progress
      end

      mind_label = clean_text(value(@xml_data, :mind_text), 256)
      field_exp = numeric_value(@xml_data, :field_exp)
      max_field_exp = numeric_value(@xml_data, :max_field_exp)
      if max_field_exp&.positive? && field_exp && field_exp >= 0
        result[:mind] = { value: field_exp, max: max_field_exp, label: mind_label }
      elsif !mind_label.empty? && (mind_value = numeric_value(@xml_data, :mind_value))
        result[:mind] = { value: mind_value, max: 100, label: mind_label }
      end

      lumnis = numeric_value(@xml_data, :lumnis)
      result[:lumnis] = { amount: lumnis } if lumnis && lumnis >= 0
      last_pulse = numeric_value(@xml_data, :last_pulse)
      result[:pulse] = { at: last_pulse } if last_pulse&.positive?
      result.empty? ? nil : result
    end

    def known_spells
      return unless ready? && @spells&.respond_to?(:known)

      spells = Array(@spells.known).filter_map do |spell|
        number = clean_text(value(spell, :num), 16)
        name = clean_text(value(spell, :name), 256)
        circle = clean_text(value(spell, :circle_name), 160)
        circle = clean_text(value(spell, :circlename), 160) if circle.empty?
        next unless number.match?(/\A\d+\z/) && !name.empty? && !circle.empty?

        { number: number, name: name, circle: circle }
      end
      { clear: true, spells: spells.sort_by { |spell| spell.fetch(:number).to_i }.first(MAX_ITEMS) }
    rescue StandardError
      nil
    end

    def cooldowns
      return unless ready? && @cooldowns&.respond_to?(:to_h)

      raw = @cooldowns.to_h
      return unless raw.is_a?(Hash)

      named = raw.select { |key, _end_time| key.is_a?(String) }
      selected = named.empty? ? raw : named
      current_time = @clock.now.to_f
      entries = selected.filter_map do |key, expiration|
        end_time = expiration.respond_to?(:to_f) ? expiration.to_f : nil
        next unless end_time&.finite? && end_time >= 0

        name = cooldown_name(key)
        next if name.empty?

        {
          id: clean_text(key, 160), name: name, active: end_time > current_time,
          end_time: end_time, remaining_seconds: [end_time - current_time, 0].max.round
        }
      end
      { clear: true, cooldowns: entries.sort_by { |entry| entry.fetch(:name) }.first(128) }
    rescue StandardError
      nil
    end

    private

    def constant(name)
      Object.const_defined?(name) ? Object.const_get(name) : nil
    end

    def nested_constant(*names)
      names.reduce(Object) do |parent, name|
        break unless parent.const_defined?(name, false)

        parent.const_get(name, false)
      end
    rescue NameError
      nil
    end

    def now = @clock.now.utc.iso8601(3)

    def value(object, method)
      return unless object&.respond_to?(method)
      return object.public_send(method) unless @read_cache

      key = [object.object_id, method]
      return @read_cache[key] if @read_cache.key?(key)

      @read_cache[key] = object.public_send(method)
    rescue StandardError
      nil
    end

    def raw_value(object, method)
      object.public_send(method) if object&.respond_to?(method)
    rescue StandardError
      nil
    end

    def array_value(object, method) = Array(value(object, method))

    def hash_value(object, method)
      found = value(object, method)
      found.is_a?(Hash) ? found : {}
    end

    def item_id(item) = clean_text(value(item, :id), 80)

    def observed_identity(use_cache: true)
      reader = use_cache ? method(:value) : method(:raw_value)
      game = clean_text(reader.call(@xml_data, :game), 160).strip
      character = clean_text(reader.call(@xml_data, :name), 160).strip
      player_id = clean_text(reader.call(@xml_data, :player_id), 160).strip
      return if [game, character, player_id].any?(&:empty?)

      normalized = [game, character, player_id].map(&:downcase)
      { token: JSON.generate(normalized).freeze, character: character, game: game }
    end

    def synchronize_identity_locked(observed)
      token = observed&.fetch(:token)
      if token != @identity_token
        @recent_loot.clear
        @character_observations.clear
        @character_capture = nil
        @character_revision.clear
        @identity_token = token
        @character_cache_identity ||= token
      end
      @identity_token
    end

    def clean_text(input, maximum)
      clean = input.to_s.encode(Encoding::UTF_8, invalid: :replace, undef: :replace)
        .scrub.gsub(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/, '')
      clean.byteslice(0, maximum).to_s.scrub
    rescue StandardError
      ''
    end

    def numeric_value(object, method)
      found = value(object, method)
      return unless found.is_a?(Numeric) && !found.is_a?(Complex) && found.finite?

      found
    end

    def integer_value(object, method)
      found = numeric_value(object, method)
      found.to_i if found && found.to_i == found
    end

    def parent_index(containers)
      containers.each_with_object({}) do |(container_id, contents), result|
        parent_id = clean_text(container_id, 80)
        next if parent_id.empty?

        Array(contents).each do |item|
          child_id = item_id(item)
          result[child_id] = parent_id unless child_id.empty? || result.key?(child_id)
        end
      end
    end

    def inventory_item(item, id, parents, containers)
      noun = clean_text(value(item, :noun), 160)
      name = clean_text(value(item, :name), 512)
      full_name = clean_text(value(item, :full_name), 1_000)
      return if noun.empty? || name.empty? || full_name.empty?

      parent_id = parents[id]
      result = {
        id: id, noun: noun, name: name, full_name: full_name,
        kind: item_kind(item, id, containers),
        capabilities: item_capabilities(item, id, parents, containers),
        ancestry: ancestry_for(id, parents)
      }
      result[:parent_id] = parent_id if parent_id
      open = explicit_boolean(item, :open?)
      open = explicit_boolean(item, :open) if open.nil?
      result[:open] = open unless open.nil?
      weight = numeric_value(item, :weight)
      result[:weight] = weight if weight && weight >= 0
      result
    end

    def item_kind(item, id, containers)
      return 'container' if containers.keys.any? { |container_id| clean_text(container_id, 80) == id }

      types = clean_text(value(item, :type), 1_000).split(',')
      return 'scroll' if types.include?('scroll')
      return 'jewelry' if types.include?('jewelry')
      return 'weapon' if types.include?('weapon')
      return 'armor' if types.include?('armor')
      return 'consumable' if (types & %w[food herb]).any?

      'item'
    end

    def item_capabilities(item, id, parents, containers)
      capabilities = %w[look inspect put]
      capabilities << 'get' if parents.key?(id)
      kind = item_kind(item, id, containers)
      capabilities.concat(%w[look_in open close]) if kind == 'container'
      capabilities << 'read' if kind == 'scroll'
      types = clean_text(value(item, :type), 1_000).split(',')
      capabilities << 'wave' if types.include?('wand')
      capabilities.uniq
    end

    def ancestry_for(id, parents)
      ancestry = []
      seen = { id => true }
      current = parents[id]
      while current && ancestry.length < MAX_ANCESTRY && !seen[current]
        ancestry << current
        seen[current] = true
        current = parents[current]
      end
      ancestry.reverse
    end

    def explicit_boolean(object, method)
      found = value(object, method)
      found if found == true || found == false
    end

    def roundtime
      ending = numeric_value(@xml_data, :roundtime_end)
      return 0 unless ending

      offset = numeric_value(@xml_data, :server_time_offset) || 0
      [ending - @clock.now.to_f + offset, 0].max.ceil
    end

    def cooldown_name(key)
      return clean_text(key, 256) if key.is_a?(String)

      spell_class = constant(:Spell)
      spell = spell_class[key] if spell_class&.respond_to?(:[])
      clean_text(value(spell, :name), 256)
    rescue StandardError
      ''
    end

    def hub_snapshot(context, session_payload, combat_payload)
      return unless session_payload[:active]

      generation = clean_text(context[:generation], 128)
      return if generation.empty?

      scripts = Array(context[:scripts]).map { |name| clean_text(name, 128) }
        .reject(&:empty?).uniq.sort.first(100)
      metadata = combat_payload[:metadata].is_a?(Hash) ? combat_payload[:metadata] : {}
      room_title = clean_text(value(@xml_data, :room_title), 256)
      current_room = value(@map, :current)
      room_id = clean_text(value(current_room, :id), 80)
      room = if !room_id.empty? || !room_title.empty?
               { id: room_id.empty? ? nil : room_id, title: room_title.empty? ? nil : room_title }
             end
      state = {
        character: session_payload.fetch(:character),
        generation: generation,
        session_id: generation,
        room: room,
        vitals: {
          health: hub_vital(:health, :max_health),
          mana: hub_vital(:mana, :max_mana),
          spirit: hub_vital(:spirit, :max_spirit),
          stamina: hub_vital(:stamina, :max_stamina)
        },
        stance: combat_payload[:stance],
        roundtime: combat_payload.fetch(:roundtime, 0),
        stunned: metadata[:stunned],
        dead: metadata[:dead],
        mind: numeric_value(@xml_data, :mind_value)&.to_i,
        encumbrance: metadata[:encumbrance],
        hands: {
          right: hub_live_object(value(@game_obj, :right_hand)),
          left: hub_live_object(value(@game_obj, :left_hand))
        },
        wounds: hub_wounds,
        active_spells: hub_active_spells(Array(context[:inactive_spell_ids]).map(&:to_s)),
        nearby: hub_room_objects,
        scripts: scripts,
        owners: context[:owners].is_a?(Hash) ? context[:owners].dup : {},
        script_status: context[:script_status].is_a?(Hash) ? context[:script_status].dup : {}
      }
      state[:character_data] = character_data
      state[:game] = session_payload.fetch(:game)
      state
    end

    def cached_character_data(level)
      infomon = @infomon || nested_constant(:Lich, :Gemstone, :Infomon) || constant(:Infomon)
      cache = value(infomon, :cache)
      values = value(cache, :to_h)
      values = values.is_a?(Hash) ? values.dup : {}
      values = {} unless @character_cache_identity == @identity_token
      stats = STAT_CODES.to_h do |name, code|
        fields = { value: "stat.#{name}", bonus: "stat.#{name}_bonus",
                   base_value: "stat.#{name}.base", base_bonus: "stat.#{name}.base_bonus",
                   enhanced_value: "stat.#{name}.enhanced", enhanced_bonus: "stat.#{name}.enhanced_bonus" }
        [code, fields.filter_map { |field, key| [field, values[key]] if values[key].is_a?(Integer) }.to_h]
      end.reject { |_code, fields| fields.empty? }
      skills = values.filter_map do |key, rank|
        match = key.to_s.match(/\Askill\.([a-z_]+)\z/)
        next unless match && !match[1].end_with?('_bonus') && rank.is_a?(Integer) && rank >= 0

        fields = { ranks: rank }
        bonus = values["skill.#{match[1]}_bonus"]
        fields[:bonus] = bonus if bonus.is_a?(Integer) && bonus >= 0
        [match[1], fields]
      end.first(64).to_h
      circles = values.filter_map do |key, rank|
        match = key.to_s.match(/\Aspell\.([a-z_]+)\z/)
        [match[1], rank] if match && rank.is_a?(Integer) && rank >= 0
      end.first(32).to_h
      info = { stats: stats }
      info[:level] = level if level
      %w[profession race].each do |field|
        text = values["stat.#{field}"]
        info[field.to_sym] = clean_text(text, 160) if text.is_a?(String) && !text.empty?
      end
      { info: info, skills: { skills: skills, spell_circles: circles, training_points: {} } }
    end

    def capture_character_row(line)
      capture = @character_capture
      return if capture[:terminal]

      if capture[:category] == :info
        if (details = line.match(/\AGender:.*?\bLevel:\s*(\d+)\z/))
          capture[:level] = details[1].to_i
          capture[:values][:level] = details[1].to_i
        elsif (stat = line.match(/\A[A-Za-z]+ \((STR|CON|DEX|AGI|DIS|AUR|LOG|INT|WIS|INF)\):\s*(.+)\z/))
          columns = stat[2].scan(/(-?\d+)\s*\((-?\d+)\)/).map { |pair| pair.map(&:to_i) }
          if [2, 3].include?(columns.length)
            normal, enhanced = columns.last(2)
            fields = { value: normal[0], bonus: normal[1], enhanced_value: enhanced[0], enhanced_bonus: enhanced[1] }
            fields.merge!(base_value: columns[0][0], base_bonus: columns[0][1]) if columns.length == 3
            capture[:values][:stats][stat[1]] = fields
          end
        elsif line.match?(/\AMana:\s*-?[\d,]+\s+Silver:\s*-?[\d,]+\z/)
          capture[:terminal] = capture[:values][:stats].length == 10
        end
      elsif line == 'Spell Lists'
        capture[:spell_lists] = true
      elsif (points = line.match(/\ATraining Points:\s*(\d+) Phy\s+(\d+) Mnt/))
        capture[:values][:training_points] = { physical: points[1].to_i, mental: points[2].to_i }
        capture[:terminal] = !capture[:overflow]
      elsif (row = line.match(/\A(.+?)\.{2,}\|\s*(\d+)(?:\s+(\d+))?\s*\z/))
        name = row[1].strip.downcase.tr(' -', '_').gsub(/_+/, '_')
        if capture[:spell_lists] && row[3].nil?
          if capture[:values][:spell_circles].length < 32
            capture[:values][:spell_circles][name] = row[2].to_i
          else
            capture[:overflow] = true
          end
        elsif !capture[:spell_lists] && row[3]
          if capture[:values][:skills].length < 64
            capture[:values][:skills][name] = { bonus: row[2].to_i, ranks: row[3].to_i }
          else
            capture[:overflow] = true
          end
        end
      end
    end

    def hub_vital(current_method, maximum_method)
      {
        current: (numeric_value(@xml_data, current_method) || 0).to_i,
        max: (numeric_value(@xml_data, maximum_method) || 0).to_i
      }
    end

    def hub_live_object(object)
      return unless object

      id = clean_text(value(object, :id), 80)
      full_name = clean_text(value(object, :full_name), 240)
      name = full_name.empty? ? clean_text(value(object, :name), 240) : full_name
      return if id.empty? || name.empty?

      { id: id, name: name }
    end

    def hub_room_objects
      objects = Array(value(@game_obj, :npcs))
      creatures = []
      corpses = []
      objects.each do |object|
        id = clean_text(value(object, :id), 80)
        next if id.empty?

        entry = {
          id: id,
          noun: clean_text(value(object, :noun), 120),
          name: clean_text(value(object, :name), 240)
        }
        if clean_text(value(object, :status), 80).match?(/dead/i)
          corpses << entry
        else
          creatures << entry
        end
      end
      { creatures: creatures.first(100), corpses: corpses.first(100) }
    end

    def hub_wounds
      injuries = value(@xml_data, :injuries)
      return {} unless injuries.respond_to?(:each)

      injuries.each_with_object({}) do |(part, levels), result|
        next unless levels.respond_to?(:[])

        wound = (levels['wound'] || levels[:wound]).to_i
        scar = (levels['scar'] || levels[:scar]).to_i
        result[part.to_s] = { wound: wound, scar: scar } if wound.positive? || scar.positive?
      end
    end

    def hub_active_spells(suppressed)
      return [] unless @active_spells&.respond_to?(:active)

      Array(value(@active_spells, :active)).filter_map do |spell|
        number = clean_text(value(spell, :num), 16)
        next if number.empty? || suppressed.include?(number)

        entry = { id: number }
        remaining = numeric_value(spell, :timeleft)
        entry[:remaining_seconds] = [remaining, 0].max.round if remaining
        entry
      end.first(256)
    end
  end

end
