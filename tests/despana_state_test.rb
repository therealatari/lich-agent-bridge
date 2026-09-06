# frozen_string_literal: true

require 'json'
require 'minitest/autorun'

require_relative '../lich/despana-state-core'

class DespanaStateTest < Minitest::Test
  FakeItem = Struct.new(:id, :noun, :name, :full_name, :type, :known_open, :weight) do
    def open? = known_open
  end
  FakeSpell = Struct.new(:num, :name, :circle_name)

  class FakeClock
    attr_accessor :now

    def initialize
      @now = Time.utc(2026, 9, 1, 12, 0, 0)
    end
  end

  class FakeState
    attr_accessor :name, :game, :player_id, :bounty_task, :society_task, :current_target_id,
                  :stance_text, :roundtime_end, :server_time_offset, :indicator,
                  :encumbrance_value, :level, :next_level_text, :next_level_value,
                  :until_next, :mind_text, :mind_value, :field_exp, :max_field_exp,
                  :lumnis, :last_pulse
  end

  class FakeObjects
    attr_accessor :inv, :containers, :right_hand, :left_hand, :target
  end

  class FakeSpells
    attr_accessor :known
  end

  class FakeCooldowns
    attr_accessor :entries

    def to_h = entries
  end

  FakeStats = Struct.new(:profession)

  def setup
    @clock = FakeClock.new
    @xml = FakeState.new
    @xml.name = 'Testmage'
    @xml.game = 'GSIV'
    @xml.player_id = '12345'
    @xml.bounty_task = 'Cull five test constructs.'
    @xml.society_task = 'Collect one task token.'
    @xml.current_target_id = '700'
    @xml.stance_text = 'guarded'
    @xml.roundtime_end = @clock.now.to_f + 2
    @xml.server_time_offset = 0
    @xml.indicator = { 'IconSTUNNED' => 'n', 'IconDEAD' => 'n' }
    @xml.encumbrance_value = 0
    @xml.level = 24
    @xml.next_level_text = '30000 until next level'
    @xml.next_level_value = 70
    @xml.until_next = 30_000
    @xml.mind_text = 'clear as a bell'
    @xml.mind_value = 10
    @xml.field_exp = 100
    @xml.max_field_exp = 1_000
    @xml.lumnis = 2
    @xml.last_pulse = @clock.now.to_i - 20

    @pack = FakeItem.new('100', 'satchel', 'black satchel', 'a black satchel', nil, true, 3)
    @scroll = FakeItem.new('101', 'scroll', 'aged scroll', 'an aged scroll', 'scroll,magic', nil, nil)
    @staff = FakeItem.new('102', 'runestaff', 'oak staff', 'an oak staff', 'weapon', nil, 4)
    @target = FakeItem.new('700', 'construct', 'test construct', 'a test construct', nil, nil, nil)
    @objects = FakeObjects.new
    @objects.inv = [@pack]
    @objects.containers = { '100' => [@scroll] }
    @objects.right_hand = @staff
    @objects.left_hand = nil
    @objects.target = @target

    @spells = FakeSpells.new
    @spells.known = [FakeSpell.new(718, 'Torment', 'Sorcerer')]
    @cooldowns = FakeCooldowns.new
    @cooldowns.entries = { 'MStrike Cooldown' => @clock.now + 12 }
    @stats = FakeStats.new('Sorcerer')
    @source = DespanaFrontendState::LichSource.new(
      xml_data: @xml, game_obj: @objects, spells: @spells,
      cooldowns: @cooldowns, stats: @stats, clock: @clock
    )
  end

  def decode(frame)
    match = frame.match(/\A<despanaState version="1" type="(?<type>[a-z_]+)" encoding="base64-json" payload="(?<payload>[A-Za-z0-9+\/]*={0,2})"\/>\z/)
    [match['type'], JSON.parse(match['payload'].unpack1('m0'))]
  end

  def info_lines(character = 'Testmage')
    [
      "Name: #{character} Race: Human Profession: Sorcerer (not shown)",
      'Gender: Male Age: 40 Expr: 100000 Level: 24',
      *LichState::STAT_CODES.map { |name, code| "#{name.capitalize} (#{code}): 100 (25) ... 35 (30)" },
      'Mana: 300 Silver: 0'
    ]
  end

  def skills_lines(character = 'Testmage')
    [
      "#{character} (at level 24), your current skill bonuses and ranks (including all modifiers) are:",
      'Arcane Symbols........| 190 25',
      'Sorcerous Lore - Necromancy........| 25 20',
      'Spell Lists', 'Sorcerer........| 35',
      'Training Points: 10 Phy 20 Mnt'
    ]
  end

  def test_character_cache_preserves_unknown_vs_zero_and_ascended_vs_base_stats
    cache = {
      'stat.aura' => 105, 'stat.aura_bonus' => 27,
      'stat.aura.enhanced' => 115, 'stat.aura.enhanced_bonus' => 32,
      'skill.arcane_symbols' => 0, 'skill.harness_power' => 25,
      'skill.harness_power_bonus' => 190, 'spell.sorcerer' => 35
    }
    infomon = Struct.new(:cache).new(cache)
    source = LichState::LichSource.new(xml_data: @xml, infomon: infomon, clock: @clock)
    data = source.character_data
    assert_equal 105, data.dig(:info, :values, :stats, 'AUR', :value)
    refute data.dig(:info, :values, :stats, 'AUR').key?(:base_value)
    assert_equal 0, data.dig(:skills, :values, :skills, 'arcane_symbols', :ranks)
    refute data.dig(:skills, :values, :skills).key?('sorcerous_lore_necromancy')
    assert_equal 'infomon_cache', data.dig(:info, :source)
    refute data.dig(:info, :complete)
    assert_nil data.dig(:info, :observed_at)
  end

  def test_complete_info_requires_matching_header_ten_stats_terminal_and_prompt
    @source.observe_character_data('', info_lines)
    refute @source.character_data.dig(:info, :complete)
    @source.observe_character_data('<prompt time="1">&gt;</prompt>', [])
    data = @source.character_data
    assert data.dig(:info, :complete)
    assert_equal 24, data.dig(:info, :observed_level)
    assert_equal 'info', data.dig(:info, :source)
    assert_equal 35, data.dig(:info, :values, :stats, 'STR', :enhanced_value)
    previous = data.dig(:info, :observed_at)
    @clock.now += 1
    @source.observe_character_data('<prompt/>', info_lines)
    # XML prompt requires a normal prompt element, not a guessed text marker.
    assert_equal previous, @source.character_data.dig(:info, :observed_at)
    @source.observe_character_data('<prompt time="2">&gt;</prompt>', [])
    assert_operator @source.character_data.dig(:info, :observed_at), :>, previous
    assert_equal 2, @source.character_recon_revision(:info)
  end

  def test_partial_and_other_characters_responses_are_not_complete
    @source.observe_character_data('<prompt time="1">&gt;</prompt>', info_lines('Testwarrior'))
    refute @source.character_data.dig(:info, :complete)
    @source.observe_character_data('<prompt time="2">&gt;</prompt>', info_lines.reject { |line| line.include?('(STR)') })
    refute @source.character_data.dig(:info, :complete)
    @source.observe_character_data('<prompt time="3">&gt;</prompt>', skills_lines.reject { |line| line.start_with?('Training Points:') })
    refute @source.character_data.dig(:skills, :complete)
  end

  def test_skills_capture_includes_spell_ranks_and_resets_on_level_or_character_change
    @source.observe_character_data('<prompt time="1">&gt;</prompt>', skills_lines)
    data = @source.character_data
    assert data.dig(:skills, :complete)
    assert_equal 20, data.dig(:skills, :values, :skills, 'sorcerous_lore_necromancy', :ranks)
    assert_equal 35, data.dig(:skills, :values, :spell_circles, 'sorcerer')
    assert_equal 20, data.dig(:skills, :values, :training_points, :mental)
    @xml.level = 25
    refute @source.character_data.dig(:skills, :complete)
    assert_equal 25, @source.character_data.dig(:info, :values, :level)
    @xml.name = 'Testwarrior'
    @xml.player_id = 'other'
    assert_empty @source.character_data.dig(:skills, :values, :skills)
    assert_equal 0, @source.character_recon_revision(:skills)
  end

  def test_inventory_uses_live_ids_and_explicit_container_ancestry
    items = @source.inventory.fetch(:items).to_h { |item| [item.fetch(:id), item] }

    assert_equal 'container', items.fetch('100').fetch(:kind)
    assert_equal %w[look inspect put look_in open close], items.fetch('100').fetch(:capabilities)
    assert_equal true, items.fetch('100').fetch(:open)
    assert_equal 3, items.fetch('100').fetch(:weight)
    assert_equal 'scroll', items.fetch('101').fetch(:kind)
    assert_equal %w[look inspect put get read], items.fetch('101').fetch(:capabilities)
    assert_equal ['100'], items.fetch('101').fetch(:ancestry)
    assert_equal '100', items.fetch('101').fetch(:parent_id)
    refute items.fetch('101').key?(:open)
  end

  def test_explicit_lich_state_populates_typed_non_story_payloads
    assert_equal({
                   active: true, identity: '["gsiv","testmage","12345"]',
                   character: 'Testmage', game: 'GSIV', profession: 'Sorcerer'
                 }, @source.session)
    assert_equal 'Cull five test constructs.', @source.bounty.dig(:task, :text)
    assert_equal ['Collect one task token.'], @source.society.fetch(:tasks).map { |task| task.fetch(:text) }
    assert_equal({ id: '700', noun: 'construct', name: 'test construct' }, @source.combat.fetch(:target))
    assert_equal({ value: 100, max: 1_000, label: 'clear as a bell' }, @source.experience.fetch(:mind))
    assert_equal '718', @source.known_spells.dig(:spells, 0, :number)
    assert_equal 12, @source.cooldowns.dig(:cooldowns, 0, :remaining_seconds)
  end

  def test_one_memoized_extraction_projects_frontend_and_hub_state
    reads = Hash.new(0)
    stance = @xml.stance_text
    right_hand = @objects.right_hand
    @xml.define_singleton_method(:stance_text) do
      reads[:stance] += 1
      stance
    end
    @objects.define_singleton_method(:right_hand) do
      reads[:right_hand] += 1
      right_hand
    end

    sample = @source.extract(
      projection_types: %i[combat inventory],
      hub_context: {
        generation: 'generation-1',
        inactive_spell_ids: [],
        scripts: ['lab-bridge'],
        owners: { movement: nil, combat: nil },
        script_status: { 'lab-bridge' => 'running' }
      }
    )

    assert_equal 1, reads[:stance]
    assert_equal 1, reads[:right_hand]
    assert_equal 'guarded', sample.projections.dig(:combat, :stance)
    assert_equal 'guarded', sample.hub.fetch(:stance)
    assert_equal '102', sample.hub.dig(:hands, :right, :id)
    assert_equal ['lab-bridge'], sample.hub.fetch(:scripts)
  end

  def test_shared_extractor_matches_both_projection_replay_fixtures
    sample = @source.extract(
      projection_types: [:combat],
      hub_context: {
        generation: 'generation-1',
        inactive_spell_ids: [],
        scripts: ['lab-bridge'],
        owners: { movement: nil, combat: nil },
        script_status: { 'lab-bridge' => 'running' }
      }
    )
    actual = {
      frontend_combat: sample.projections.fetch(:combat),
      hub: {
        character: sample.hub.fetch(:character),
        generation: sample.hub.fetch(:generation),
        stance: sample.hub.fetch(:stance),
        roundtime: sample.hub.fetch(:roundtime),
        stunned: sample.hub.fetch(:stunned),
        dead: sample.hub.fetch(:dead),
        encumbrance: sample.hub.fetch(:encumbrance),
        hands: sample.hub.fetch(:hands),
        scripts: sample.hub.fetch(:scripts),
        owners: sample.hub.fetch(:owners),
        script_status: sample.hub.fetch(:script_status)
      }
    }
    expected = JSON.parse(
      File.read(
        File.expand_path('fixtures/live-state-projections.json', __dir__),
        encoding: 'UTF-8'
      )
    )

    assert_equal expected, JSON.parse(JSON.generate(actual))
  end

  def test_default_profession_source_uses_the_real_lich_namespace
    original_lich = Object.const_get(:Lich) if Object.const_defined?(:Lich)
    Object.send(:remove_const, :Lich) if original_lich
    Object.const_set(:Lich, Module.new)
    Lich.const_set(:Gemstone, Module.new)
    Lich::Gemstone.const_set(:Stats, FakeStats.new('Warrior'))

    source = DespanaFrontendState::LichSource.new(
      xml_data: @xml, game_obj: @objects, spells: @spells,
      cooldowns: @cooldowns, clock: @clock
    )

    assert_equal 'Warrior', source.session.fetch(:profession)
  ensure
    Object.send(:remove_const, :Lich) if Object.const_defined?(:Lich)
    Object.const_set(:Lich, original_lich) if original_lich
  end

  def test_default_profession_source_can_load_after_the_publisher_source
    original_lich = Object.const_get(:Lich) if Object.const_defined?(:Lich)
    Object.send(:remove_const, :Lich) if original_lich
    source = DespanaFrontendState::LichSource.new(
      xml_data: @xml, game_obj: @objects, spells: @spells,
      cooldowns: @cooldowns, clock: @clock
    )

    Object.const_set(:Lich, Module.new)
    Lich.const_set(:Gemstone, Module.new)
    Lich::Gemstone.const_set(:Stats, FakeStats.new('Warrior'))

    assert_equal 'Warrior', source.session.fetch(:profession)
  ensure
    Object.send(:remove_const, :Lich) if Object.const_defined?(:Lich)
    Object.const_set(:Lich, original_lich) if original_lich
  end

  def test_publisher_emits_bounded_versioned_frames_only_when_state_changes
    output = []
    publisher = DespanaFrontendState::Publisher.new(source: @source, output: output.method(:<<), clock: @clock)

    frames = publisher.publish(force: true)

    assert_equal 'session', decode(frames.first).first
    assert_equal DespanaFrontendState::Publisher::INTERVALS.keys.map(&:to_s).sort,
                 frames.map { |frame| decode(frame).first }.sort
    assert frames.all? { |frame| frame.start_with?('<despanaState version="1"') }
    assert_empty publisher.publish

    @clock.now += 1
    assert publisher.record_loot([@scroll], source: 'eloot exact acquisition')
    changed = publisher.publish
    recent = changed.select { |frame| decode(frame).first == 'recent_loot' }
    assert_equal 1, recent.length
    assert_equal '101', decode(recent.first).last.dig('items', 0, 'id')
  end

  def test_forced_publish_replays_unchanged_state_for_a_late_frontend_attachment
    output = []
    publisher = DespanaFrontendState::Publisher.new(source: @source, output: output.method(:<<), clock: @clock)
    publisher.publish(force: true)
    output.clear

    replayed = publisher.publish(force: true)
    types = replayed.map { |frame| decode(frame).first }

    assert_includes types, 'session'
    assert_includes types, 'inventory'
    assert_equal ['101', '100', '102'].sort,
                 decode(replayed.find { |frame| decode(frame).first == 'inventory' }).last
                   .fetch('items').map { |item| item.fetch('id') }.sort
  end

  def test_identity_token_requires_all_explicit_fields_and_normalizes_case
    assert_equal '["gsiv","testmage","12345"]', @source.identity_token

    @xml.name = 'TESTMAGE'
    assert_equal '["gsiv","testmage","12345"]', @source.identity_token

    %i[game name player_id].each do |field|
      original = @xml.public_send(field)
      @xml.public_send("#{field}=", '')
      assert_nil @source.identity_token
      refute @source.ready?
      @xml.public_send("#{field}=", original)
      assert @source.ready?
    end
  end

  def test_incomplete_identity_publishes_only_an_inactive_session
    @xml.player_id = ''
    output = []
    publisher = DespanaFrontendState::Publisher.new(source: @source, output: output.method(:<<), clock: @clock)

    frames = publisher.publish

    assert_equal ['session'], frames.map { |frame| decode(frame).first }
    assert_equal({ 'active' => false }, decode(frames.first).last.reject { |key, _value| key == 'observed_at' })
  end

  def test_unchanged_session_is_emitted_on_heartbeat
    @xml.roundtime_end = 0
    @cooldowns.entries = {}
    output = []
    publisher = DespanaFrontendState::Publisher.new(source: @source, output: output.method(:<<), clock: @clock)
    publisher.publish

    @clock.now += 1
    frames = publisher.publish

    assert_equal ['session'], frames.map { |frame| decode(frame).first }
    assert_equal true, decode(frames.first).last.fetch('active')
  end

  def test_failed_session_output_blocks_later_state_and_retries_immediately
    output = []
    fail_session = true
    writer = proc do |frame|
      if fail_session
        fail_session = false
        raise IOError, 'frontend unavailable'
      end
      output << frame
    end
    publisher = DespanaFrontendState::Publisher.new(source: @source, output: writer, clock: @clock)

    assert_empty publisher.publish
    assert_empty output

    retried = publisher.publish
    assert_equal 'session', decode(retried.first).first
    assert_equal DespanaFrontendState::Publisher::INTERVALS.keys.map(&:to_s).sort,
                 retried.map { |frame| decode(frame).first }.sort
  end

  def test_identity_boundary_clears_recent_loot_including_missing_identity_transition
    assert @source.record_loot([@scroll], source: 'exact acquisition')
    assert_equal ['101'], @source.recent_loot.fetch(:items).map { |item| item.fetch(:id) }

    @xml.name = ''
    assert_nil @source.recent_loot
    refute @source.record_loot([@scroll], source: 'wrong character')

    @xml.name = 'Testknight'
    @xml.player_id = '67890'
    assert_empty @source.recent_loot.fetch(:items)
  end

  def test_repeated_missing_identity_is_inert_and_restore_forces_equal_snapshots
    output = []
    publisher = DespanaFrontendState::Publisher.new(source: @source, output: output.method(:<<), clock: @clock)
    expected_types = DespanaFrontendState::Publisher::INTERVALS.keys.map(&:to_s).sort

    assert_equal expected_types, publisher.publish.map { |frame| decode(frame).first }.sort
    assert_empty publisher.publish

    @xml.name = ''
    inactive = publisher.publish
    assert_equal ['session'], inactive.map { |frame| decode(frame).first }
    assert_equal false, decode(inactive.first).last.fetch('active')
    assert_empty publisher.publish

    forced_inactive = publisher.publish(force: true)
    assert_equal ['session'], forced_inactive.map { |frame| decode(frame).first }

    @xml.name = 'Testmage'
    restored = publisher.publish
    assert_equal 'session', decode(restored.first).first
    assert_equal expected_types, restored.map { |frame| decode(frame).first }.sort
  end

  def test_direct_character_switch_resets_signatures_and_does_not_publish_prior_loot
    output = []
    publisher = DespanaFrontendState::Publisher.new(source: @source, output: output.method(:<<), clock: @clock)
    assert publisher.record_loot([@scroll], source: 'Testmage acquisition')
    publisher.publish(force: true)

    @xml.name = 'Testknight'
    @xml.player_id = '67890'
    frames = publisher.publish
    decoded = frames.to_h { |frame| decode(frame) }

    assert_equal 'session', decode(frames.first).first
    assert_equal 'Testknight', decoded.fetch('session').fetch('character')
    assert_equal DespanaFrontendState::Publisher::INTERVALS.keys.map(&:to_s).sort, decoded.keys.sort
    assert_empty decoded.fetch('recent_loot').fetch('items')
  end

  def test_direct_switch_publishes_session_before_available_feeds
    output = []
    publisher = DespanaFrontendState::Publisher.new(source: @source, output: output.method(:<<), clock: @clock)
    publisher.publish
    @source.define_singleton_method(:known_spells) { nil }

    @xml.name = 'Testknight'
    @xml.player_id = '67890'
    frames = publisher.publish
    types = frames.map { |frame| decode(frame).first }

    assert_equal 'session', types.first
    refute_includes types, 'known_spells'
    assert_includes types, 'inventory'
    assert_equal 'Testknight', decode(frames.first).last.fetch('character')
  end

  def test_mid_poll_identity_change_discards_the_entire_mixed_batch
    output = []
    publisher = DespanaFrontendState::Publisher.new(source: @source, output: output.method(:<<), clock: @clock)
    xml = @xml
    changed = false
    @source.define_singleton_method(:bounty) do
      unless changed
        changed = true
        xml.name = 'Testknight'
        xml.player_id = '67890'
      end
      super()
    end

    assert_empty publisher.publish(force: true)
    assert_empty output

    stable = publisher.publish
    assert_equal DespanaFrontendState::Publisher::INTERVALS.keys.map(&:to_s).sort,
                 stable.map { |frame| decode(frame).first }.sort
  end

  def test_record_loot_final_identity_recheck_clears_a_mutating_record
    reads = 0
    @xml.define_singleton_method(:player_id) do
      reads += 1
      reads >= 3 ? '67890' : '12345'
    end

    refute @source.record_loot([@scroll], source: 'old character acquisition')
    assert_empty @source.recent_loot.fetch(:items)
    assert_equal '["gsiv","testmage","67890"]', @source.identity_token
  end

  def test_concurrent_identity_clear_cannot_be_overwritten_by_old_loot_record
    started = Queue.new
    resume_record = Queue.new
    original_name = @scroll.name
    @scroll.define_singleton_method(:name) do
      started << true
      resume_record.pop
      original_name
    end

    recorder = Thread.new do
      @source.record_loot([@scroll], source: 'old character acquisition')
    end
    started.pop
    @xml.name = 'Testknight'
    @xml.player_id = '67890'
    assert_equal '["gsiv","testknight","67890"]', @source.identity_token
    resume_record << true

    refute recorder.value
    assert_empty @source.recent_loot.fetch(:items)
  end

  def test_unknown_values_are_omitted_instead_of_inferred
    @objects.containers = {}
    @pack.known_open = nil
    @pack.weight = nil
    item = @source.inventory.fetch(:items).find { |entry| entry.fetch(:id) == '100' }

    assert_equal 'item', item.fetch(:kind)
    assert_equal %w[look inspect put], item.fetch(:capabilities)
    refute item.key?(:open)
    refute item.key?(:weight)
  end

  def test_envelope_rejects_payloads_beyond_the_frontend_limit
    error = assert_raises(ArgumentError) do
      DespanaFrontendState::Envelope.encode(:inventory, items: [{ name: 'x' * DespanaFrontendState::MAX_DECODED_BYTES }])
    end

    assert_equal 'structured-state payload is too large', error.message
  end
end
