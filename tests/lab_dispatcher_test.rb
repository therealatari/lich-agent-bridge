require 'minitest/autorun'

LabDispatcherScript = Struct.new(:vars)

module Script
  class << self
    attr_accessor :current_script, :running_names, :started, :killed
  end

  def self.current = current_script
  def self.running?(name) = Array(running_names).include?(name)

  def self.start(name)
    self.started = name
    Object.new
  end

  def self.kill(name)
    self.killed = name
  end
end

module LichAgentBridge
  class << self
    attr_accessor :dispatched
  end

  def self.handle_command(command)
    self.dispatched = command
  end
end

def respond(message)
  ($lab_dispatcher_responses ||= []) << message
end

class LabDispatcherTest < Minitest::Test
  SCRIPT_PATH = File.expand_path('../lich/lab.lic', __dir__)

  def setup
    $lab_dispatcher_responses = []
    Script.current_script = LabDispatcherScript.new([''])
    Script.running_names = []
    Script.started = nil
    Script.killed = nil
    LichAgentBridge.dispatched = nil
  end

  def run_dispatcher(command)
    Script.current_script = LabDispatcherScript.new([command])
    load SCRIPT_PATH
  end

  def test_default_command_starts_hidden_bridge
    run_dispatcher('')

    assert_equal 'lab-bridge', Script.started
    assert_includes $lab_dispatcher_responses.last, 'starting agent bridge'
  end

  def test_start_is_idempotent
    Script.running_names = ['lab-bridge']

    run_dispatcher('start')

    assert_nil Script.started
    assert_includes $lab_dispatcher_responses.last, 'already running'
  end

  def test_help_works_without_running_bridge
    run_dispatcher('help')

    assert_nil Script.started
    help = $lab_dispatcher_responses.join("\n")
    assert_includes help, ';lab status'
    assert_includes help, ', QUESTION'
    assert_includes help, 'sources'
    assert_includes help, 'context'
    assert_includes help, 'forget'
  end

  def test_management_command_dispatches_to_running_bridge
    Script.running_names = ['lab-bridge']

    run_dispatcher('status')

    assert_equal 'status', LichAgentBridge.dispatched
  end

  def test_stop_kills_hidden_bridge
    Script.running_names = ['lab-bridge']

    run_dispatcher('stop')

    assert_equal 'lab-bridge', Script.killed
    assert_includes $lab_dispatcher_responses.last, 'agent bridge stopped'
  end
end
