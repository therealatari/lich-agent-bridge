require 'json'
require 'minitest/autorun'
require 'tempfile'

load File.expand_path('../lich/lab-controller-registry.rb', __dir__)

class LabControllerRegistryTest < Minitest::Test
  def setup
    @path = File.expand_path('fixtures/controllers.json', __dir__)
    @registry = LabControllerRegistry.load(@path)
  end

  def test_shipped_registry_is_empty_and_does_not_allow_test_controllers
    registry = LabControllerRegistry.load(File.expand_path('../lich/lab-controllers.json', __dir__))
    assert_empty registry.controllers
    assert_empty registry.safe_patterns
    assert_nil registry.match('lab-test-hunt start test-hunt')
  end

  def test_manifest_exposes_all_controllers_and_testknight_hunt_contract
    assert_equal %w[engage room hunt rift], @registry.controllers.map(&:name)
    hunt = @registry.controller('hunt')
    assert_equal ['Testknight'], hunt.characters
    assert_equal %w[movement combat], hunt.lanes
    assert_equal '$lab_hunt_result', hunt.result_global
    assert_equal 'profile_room', hunt.safe_handoff.fetch('kind')
    assert_equal '1000', hunt.safe_handoff.fetch('rooms').fetch('test-hunt')
  end

  def test_exact_anchored_grammar_matches_and_canonicalizes_arguments
    engagement = @registry.match('LAB-TEST-ENGAGE TEST-LIVING #185539534 LOOT')
    assert_equal 'engage', engagement.controller.name
    assert_equal 'start', engagement.action.name
    assert_equal 'test-living', engagement.arguments.fetch('profile')
    assert_equal '185539534', engagement.arguments.fetch('target_id')
    assert engagement.arguments.fetch('loot')
    assert_equal 'test-living #185539534 loot', engagement.script_args

    hunt = @registry.match('lab-test-hunt start test-hunt')
    assert_equal({ 'profile' => 'test-hunt' }, hunt.arguments)
    assert_nil @registry.match('lab-test-hunt start other-profile')
    assert_nil @registry.match('lab-test-hunt start test-hunt; north')
  end

  def test_capability_action_builds_exact_command_and_schema
    action = @registry.controller('hunt').action('start')
    built = action.build(profile: 'test-probe')
    assert_equal 'lab-test-hunt start test-probe', built.fetch(:command)
    assert_equal false, action.argument_schema.fetch('additionalProperties')
    assert_raises(LabControllerRegistry::ManifestError) do
      action.build(profile: 'test-hunt', extra: 'no')
    end
  end

  def test_invalid_manifest_fails_closed
    raw = JSON.parse(File.read(@path))
    raw.fetch('controllers').first['surprise'] = true
    file = Tempfile.new(['bad-controller-manifest', '.json'])
    file.write(JSON.generate(raw))
    file.close

    error = assert_raises(LabControllerRegistry::ManifestError) do
      LabControllerRegistry.load(file.path)
    end
    assert_match(/unsupported field/, error.message)
  ensure
    file&.unlink
  end
end
