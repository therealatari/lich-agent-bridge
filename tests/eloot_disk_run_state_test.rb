# frozen_string_literal: true

require 'minitest/autorun'
require 'ostruct'

ELOOT_SOURCE = ENV.fetch('ELOOT_SOURCE') do
  abort 'Set ELOOT_SOURCE to the explicit local eloot.lic source to test.'
end

module DownstreamHook
  def self.list = ['eloot_diskintegration']
end

module Disk
  class << self
    attr_accessor :mine
  end
end

module GameObj
  class << self
    attr_accessor :objects

    def [](id)
      objects.fetch(id)
    end
  end
end

module ELoot
  class << self
    attr_accessor :test_data

    def data = test_data
  end
end

source = File.read(ELOOT_SOURCE)
start_at = source.index("  def self.disk_usage\n") or raise 'disk_usage start not found'
end_at = source.index("  def self.reset_disk_full", start_at) or raise 'disk_usage end not found'
ELoot.module_eval(
  source[start_at...end_at],
  ELOOT_SOURCE,
  source[0...start_at].count("\n") + 1
)

class ELootDiskRunStateTest < Minitest::Test
  def setup
    Disk.mine = nil
    GameObj.objects = {}
    ELoot.test_data = OpenStruct.new(settings: { use_disk: true }, disk: nil)
  end

  def test_repeated_eloot_run_seeds_disk_even_when_persistent_hook_exists
    disk = Struct.new(:id).new(401)
    Disk.mine = disk
    GameObj.objects = { disk.id => disk }

    ELoot.disk_usage

    assert_same disk, ELoot.data.disk
  end
end
