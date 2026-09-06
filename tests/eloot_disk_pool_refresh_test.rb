# frozen_string_literal: true

require 'minitest/autorun'
require 'ostruct'

ELOOT_SOURCE = ENV.fetch('ELOOT_SOURCE') do
  abort 'Set ELOOT_SOURCE to the explicit local eloot.lic source to test.'
end

FakeItem = Struct.new(:id, :type, :contents, :name)

module GameObj
  class << self
    attr_accessor :right_hand, :left_hand
  end
end

module Inventory
  class << self
    attr_accessor :dragged

    def free_hands(both: false)
      return unless both

      GameObj.right_hand = FakeItem.new(nil, '', [], 'Empty')
      GameObj.left_hand = FakeItem.new(nil, '', [], 'Empty')
    end

    def drag(box)
      self.dragged = box
      GameObj.right_hand = box
    end

    def single_drag(_box); end
  end
end

module Loot
  def self.box_loot(*); end
end

module ELoot
  class << self
    attr_accessor :test_data, :commands, :disk_box, :find_boxes_calls

    def data = test_data
    def f2p? = false
    def msg(**_args); end
    def reset_disk_full; end
    def go2(_destination); end
    def find_worker = OpenStruct.new(id: 900)
    def wait_for_disk; end
    def wait_rt; end
    def box_unphase(box) = box

    def find_boxes
      self.find_boxes_calls += 1
      [disk_box]
    end
  end
end

def dothistimeout(command, _timeout, _match)
  ELoot.commands << command
  'takes your box, totaling 150 silvers'
end

source = File.read(ELOOT_SOURCE)
start_at = source.index("    def self.locksmith_pool(boxes, deposit = false)\n") or raise 'locksmith_pool start not found'
end_at = source.index("    def self.handle_full_pool(worker)\n", start_at) or raise 'locksmith_pool end not found'
Sell = Module.new unless defined?(Sell)
Sell.module_eval(source[start_at...end_at], ELOOT_SOURCE, source[0...start_at].count("\n") + 1)

class ELootDiskPoolRefreshTest < Minitest::Test
  def setup
    @box = FakeItem.new(101, 'box', [], 'an iron-bound box')
    empty = FakeItem.new(nil, '', [], 'Empty')
    GameObj.right_hand = empty
    GameObj.left_hand = empty
    Inventory.dragged = nil
    ELoot.disk_box = @box
    ELoot.find_boxes_calls = 0
    ELoot.commands = []
    ELoot.test_data = OpenStruct.new(
      settings: {
        use_standard_tipping: true,
        use_incremental_tipping: false,
        sell_locksmith_pool_tip_percent: true,
        sell_locksmith_pool_tip: 15
      },
      silver_breakdown: Hash.new(0)
    )
  end

  def test_pool_rescans_after_disk_arrives_before_submitting_boxes
    Sell.locksmith_pool([])

    assert_equal 1, ELoot.find_boxes_calls
    assert_same @box, Inventory.dragged
    assert_includes ELoot.commands, 'give #900 15 PERCENT'
  end

  def test_pool_deduplicates_republished_game_objects_by_stable_id
    stale_snapshot = FakeItem.new(@box.id, 'box', [], 'the same iron-bound box')

    Sell.locksmith_pool([stale_snapshot])

    assert_same @box, Inventory.dragged
    assert_equal 1, ELoot.commands.count { |command| command == 'give #900 15 PERCENT' }
  end
end
