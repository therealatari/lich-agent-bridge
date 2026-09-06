# frozen_string_literal: true

require 'minitest/autorun'
require 'ostruct'

ELOOT_SOURCE = ENV.fetch('ELOOT_SOURCE') do
  abort 'Set ELOOT_SOURCE to the explicit local eloot.lic source to test.'
end

class GameObj
  class << self
    attr_accessor :containers
  end

  attr_reader :id, :contents

  def initialize(id:, contents: [])
    @id = id
    @contents = contents
  end

  def empty?
    false
  end
end

module StowList
  class << self
    attr_accessor :stow_list
  end
end

module Inventory; end
module Sell; end

module ELoot
  class << self
    attr_accessor :test_data, :commands

    def data
      test_data
    end

    def msg(**_args); end

    def get_command(command, *_args, **_kwargs)
      commands << command
      command.start_with?('look in ') ? ['In the pouch you see a sapphire.'] : []
    end
  end
end

source = File.read(ELOOT_SOURCE)
open_start = source.index("    def self.open_single_container(") or raise 'open_single_container start not found'
open_end = source.index("    def self.return_hands\n", open_start) or raise 'open_single_container end not found'
Inventory.module_eval(source[open_start...open_end], ELOOT_SOURCE, source[0...open_start].count("\n") + 1)

inventory_start = source.index("    def self.check_inventory\n") or raise 'check_inventory start not found'
inventory_end = source.index("    def self.collectibles\n", inventory_start) or raise 'check_inventory end not found'
Sell.module_eval(source[inventory_start...inventory_end], ELOOT_SOURCE, source[0...inventory_start].count("\n") + 1)

class ELootSellContainerRefreshTest < Minitest::Test
  def setup
    @gem = GameObj.new(id: 101)
    @pouch = GameObj.new(id: 201, contents: [@gem])
    GameObj.containers = { @pouch.id => @pouch }
    StowList.stow_list = { gem: @pouch }
    ELoot.test_data = OpenStruct.new(
      settings: { sell_container: ['gem'], use_disk: false },
      disk: nil,
      silent_open: /./,
      look_regex: /./,
      sell_containers: []
    )
    ELoot.commands = []
    $sell_ignore = []
  end

  def test_sell_scan_refreshes_a_cached_auto_closed_container
    assert_equal [@gem], Sell.check_inventory
    assert_equal ["open ##{@pouch.id}", "look in ##{@pouch.id}"], ELoot.commands
  end
end
