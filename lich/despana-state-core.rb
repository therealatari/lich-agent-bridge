# frozen_string_literal: true

require 'json'
require 'time'
require_relative 'lich-state-core'

# Despana-only adapter from frontend-independent LichState projections to the
# private XML envelope consumed by DespanaFE. Nothing outside Despana should
# load this module.
module DespanaFrontendState
  VERSION = 1
  ENCODING = 'base64-json'
  MAX_DECODED_BYTES = LichState::MAX_DECODED_BYTES

  # Compatibility aliases keep the Despana adapter's existing test and script
  # interface stable while ownership of extraction lives in LichState.
  LichSource = LichState::LichSource
  ExtractedState = LichState::ExtractedState

  module Envelope
    module_function

    def encode(type, payload)
      json = JSON.generate(payload)
      raise ArgumentError, 'structured-state payload is too large' if json.bytesize > MAX_DECODED_BYTES

      encoded = [json].pack('m0')
      %(<despanaState version="#{VERSION}" type="#{type}" encoding="#{ENCODING}" payload="#{encoded}"/>)
    end
  end

  # Change-detecting Despana publisher with per-projection polling intervals.
  # Its only side effect is passing an inert XML frame to the supplied output.
  class Publisher
    INTERVALS = {
      session: 1, inventory: 1, bounty: 1, society: 1, recent_loot: 1,
      combat: 0.25, experience: 1, known_spells: 30, cooldowns: 1
    }.freeze

    def initialize(source:, output:, clock: Time)
      @source = source
      @output = output
      @clock = clock
      @last_checked_at = {}
      @signatures = {}
      @identity_token = nil
    end

    attr_reader :last_sample, :identity_token

    def publish(force: false, sample: nil)
      @last_sample = nil
      requested = due_types(force: force)
      sample ||= @source.extract(projection_types: requested)
      return [] unless sample

      identity_token = sample.identity_token
      if identity_token != @identity_token
        reset_for_identity(identity_token)
        force = true
        if requested != INTERVALS.keys
          sample = @source.extract(projection_types: INTERVALS.keys)
          return [] unless sample
          identity_token = sample.identity_token
          reset_for_identity(identity_token) if identity_token != @identity_token
        end
      end
      @last_sample = sample
      pending = []
      INTERVALS.each do |type, interval|
        next if identity_token.nil? && type != :session
        next unless force || due?(type, interval)

        @last_checked_at[type] = @clock.now.to_f
        payload = sample.projections[type]
        next unless payload

        payload = bounded_payload(type, payload)
        next unless payload

        signature = JSON.generate(payload)
        next unless force || type == :session || @signatures[type] != signature

        frame = Envelope.encode(type, payload.merge(observed_at: @clock.now.utc.iso8601(3)))
        pending << [type, signature, frame]
      rescue StandardError
        next
      end

      # Build a coherent batch before exposing any of it. XMLData can change
      # while a poll is in progress; discard that mixed batch and force a fresh
      # one on the next poll rather than leaking two characters into one view.
      current_identity = @source.identity_token
      if current_identity != identity_token
        @last_sample = nil
        reset_for_identity(current_identity)
        return []
      end

      frames = []
      pending.each do |type, signature, frame|
        current_identity = @source.identity_token
        if current_identity != identity_token
          @last_sample = nil
          reset_for_identity(current_identity)
          break
        end

        begin
          @output.call(frame)
          @signatures[type] = signature
          frames << frame
        rescue StandardError
          # A state batch is not safe without its leading session boundary.
          # Make that control frame immediately retryable and expose no later
          # payload from the failed batch.
          if type == :session
            @last_checked_at.clear
            break
          end
        end
      end
      frames
    end

    def record_loot(objects, source:)
      @source.record_loot(objects, source: source)
    end

    private

    def due_types(force: false)
      INTERVALS.filter_map do |type, interval|
        type if force || due?(type, interval)
      end
    end

    def reset_for_identity(identity_token)
      @last_checked_at.clear
      @signatures.clear
      @identity_token = identity_token
    end

    def due?(type, interval)
      !@last_checked_at.key?(type) || @clock.now.to_f - @last_checked_at.fetch(type) >= interval
    end

    def bounded_payload(type, payload)
      timestamp = @clock.now.utc.iso8601(3)
      return payload if JSON.generate(payload.merge(observed_at: timestamp)).bytesize <= MAX_DECODED_BYTES

      collection_key = {
        inventory: :items, society: :tasks, recent_loot: :items,
        known_spells: :spells, cooldowns: :cooldowns
      }[type]
      return unless collection_key && payload[collection_key].is_a?(Array)

      selected = []
      base = payload.merge(collection_key => [], observed_at: timestamp)
      used = JSON.generate(base).bytesize
      payload.fetch(collection_key).each do |record|
        added = JSON.generate(record).bytesize + (selected.empty? ? 0 : 1)
        break if used + added > MAX_DECODED_BYTES

        selected << record
        used += added
      end
      payload.merge(collection_key => selected)
    end
  end
end
