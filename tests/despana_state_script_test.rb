require 'minitest/autorun'

ENV['DESPANA_STATE_LIBRARY_ONLY'] = '1'

module Script
  def self.current = (@current ||= Object.new)
end

def hide_me = nil
def _respond(_message) = nil

load File.expand_path('../lich/despana-state.lic', __dir__)

class DespanaStateScriptTest < Minitest::Test
  FakePublisher = Struct.new(:calls) do
    def publish(force: false)
      calls << force
      []
    end

    def record_loot(objects, source:)
      calls << [objects, source]
      true
    end
  end

  def setup
    @original_publisher = DespanaStateBridge.instance_variable_get(:@publisher)
    @publisher = FakePublisher.new([])
    DespanaStateBridge.instance_variable_set(:@publisher, @publisher)
  end

  def teardown
    DespanaStateBridge.instance_variable_set(:@publisher, @original_publisher)
  end

  def test_refresh_control_is_consumed_and_forces_a_complete_snapshot
    assert_nil DespanaStateBridge.handle_input('<c>;send to despana-state refresh')
    assert_equal [true], @publisher.calls
  end

  def test_unrelated_frontend_input_passes_through_unchanged
    line = '<c>look'

    assert_same line, DespanaStateBridge.handle_input(line)
    assert_empty @publisher.calls
  end

  def test_attributed_loot_is_forwarded_to_the_despana_publisher
    objects = [Object.new]

    assert DespanaStateBridge.record_loot(objects, source: 'exact acquisition')
    assert_equal [[objects, 'exact acquisition']], @publisher.calls
  end
end
