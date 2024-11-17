from typing import TYPE_CHECKING, List, Callable, Union, Dict, Tuple, Optional, Iterable

from worlds.AutoWorld import CollectionState
from worlds.generic.Rules import add_rule, set_rule
from BaseClasses import Location, Entrance, Region, Req
from BaseRules import all_reqs_to_rule, any_req_to_rule, req_to_rule, complex_reqs_to_rule, RULE_ALWAYS_FALSE, RULE_ALWAYS_TRUE, AnyReq, AllReq

from .Locations import location_table, zipline_unlocks, is_location_valid, shop_locations, event_locs
from .Options import EndGoal, CTRLogic, NoTicketSkips
from .Types import HatType, ChapterIndex, hat_type_to_item, Difficulty, HitType

if TYPE_CHECKING:
    from . import HatInTimeWorld
    

act_connections = {
    "Mafia Town - Act 2": ["Mafia Town - Act 1"],
    "Mafia Town - Act 3": ["Mafia Town - Act 1"],
    "Mafia Town - Act 4": ["Mafia Town - Act 2", "Mafia Town - Act 3"],
    "Mafia Town - Act 6": ["Mafia Town - Act 4"],
    "Mafia Town - Act 7": ["Mafia Town - Act 4"],
    "Mafia Town - Act 5": ["Mafia Town - Act 6", "Mafia Town - Act 7"],

    "Battle of the Birds - Act 2": ["Battle of the Birds - Act 1"],
    "Battle of the Birds - Act 3": ["Battle of the Birds - Act 1"],
    "Battle of the Birds - Act 4": ["Battle of the Birds - Act 2", "Battle of the Birds - Act 3"],
    "Battle of the Birds - Act 5": ["Battle of the Birds - Act 2", "Battle of the Birds - Act 3"],
    "Battle of the Birds - Finale A": ["Battle of the Birds - Act 4", "Battle of the Birds - Act 5"],
    "Battle of the Birds - Finale B": ["Battle of the Birds - Finale A"],

    "Subcon Forest - Finale": ["Subcon Forest - Act 1", "Subcon Forest - Act 2",
                               "Subcon Forest - Act 3", "Subcon Forest - Act 4",
                               "Subcon Forest - Act 5"],

    "The Arctic Cruise - Act 2":  ["The Arctic Cruise - Act 1"],
    "The Arctic Cruise - Finale": ["The Arctic Cruise - Act 2"],
}


def get_cumulative_hat_costs(world: "HatInTimeWorld") -> Dict[HatType, int]:
    cost = 0
    costs = {}
    for h in world.hat_craft_order:
        cost += world.hat_yarn_costs[h]
        costs[h] = cost
    return costs


def hat_requirements(world: "HatInTimeWorld", hat: HatType) -> Optional[Req]:
    if world.options.HatItems:
        return Req(hat_type_to_item[hat], 1)
    
    if world.hat_yarn_costs[hat] <= 0:  # this means the hat was put into starting inventory
        return None
    
    return Req("Yarn", world.cumulative_hat_yarn_costs[hat])


def painting_logic(world: "HatInTimeWorld") -> bool:
    return bool(world.options.ShuffleSubconPaintings)


# -1 = Normal, 0 = Moderate, 1 = Hard, 2 = Expert
def get_difficulty(world: "HatInTimeWorld") -> Difficulty:
    return Difficulty(world.options.LogicDifficulty)


def painting_requirements(world: "HatInTimeWorld", count: int, allow_skip: bool = True) -> Optional[Req]:
    if not painting_logic(world):
        return None

    if not world.options.NoPaintingSkips and allow_skip:
        # In Moderate there is a very easy trick to skip all the walls, except for the one guarding the boss arena
        if get_difficulty(world) >= Difficulty.MODERATE:
            return None

    return Req("Progressive Painting Unlock", count)


def zipline_logic(world: "HatInTimeWorld") -> bool:
    return bool(world.options.ShuffleAlpineZiplines)


HOOKSHOT_REQ = Req("Hookshot Badge", 1)


def hit_requirements(world: "HatInTimeWorld", umbrella_only: bool = False) -> Union[Req, AnyReq, None]:
    if not world.options.UmbrellaLogic:
        return None
    
    if umbrella_only:
        return Req("Umbrella", 1)
    hat_req = hat_requirements(world, HatType.BREWING)
    if not hat_req:
        # always true
        return None
    return AnyReq([Req("Umbrella", 1), hat_req])


def relic_combo_requirements(world: "HatInTimeWorld", relic: str) -> List[Req]:
    return [Req(item, 1) for item in world.item_name_groups[relic]]


# This is used to determine if the player can clear an act that's required to unlock a Time Rift
def can_clear_required_act(state: CollectionState, world: "HatInTimeWorld", act_entrance: str) -> bool:
    entrance: Entrance = world.multiworld.get_entrance(act_entrance, world.player)
    if not state.can_reach(entrance.connected_region, "Region", world.player):
        return False

    if "Free Roam" in entrance.connected_region.name:
        return True

    name: str = f"Act Completion ({entrance.connected_region.name})"
    return world.multiworld.get_location(name, world.player).access_rule(state)


def can_clear_alpine(state: CollectionState, player: int) -> bool:
    return state.has_all(("Birdhouse Cleared", "Lava Cake Cleared",
                          "Windmill Cleared", "Twilight Bell Cleared"), player)


def can_clear_metro(state: CollectionState, player: int) -> bool:
    return state.has_all(("Nyakuza Intro Cleared", 
                          "Yellow Overpass Station Cleared",
                          "Yellow Overpass Manhole Cleared",
                          "Green Clean Station Cleared",
                          "Green Clean Manhole Cleared",
                          "Bluefin Tunnel Cleared",
                          "Pink Paw Station Cleared",
                          "Pink Paw Manhole Cleared"), player)


def precompute_costs(world: "HatInTimeWorld"):
    # First, chapter access
    starting_chapter = ChapterIndex(world.options.StartingChapter)
    world.chapter_timepiece_costs[starting_chapter] = 0
    world.cumulative_hat_yarn_costs = get_cumulative_hat_costs(world)

    # Chapter costs increase progressively. Randomly decide the chapter order, except for Finale
    chapter_list: List[ChapterIndex] = [ChapterIndex.MAFIA, ChapterIndex.BIRDS,
                                        ChapterIndex.SUBCON, ChapterIndex.ALPINE]

    final_chapter = ChapterIndex.FINALE
    if world.options.EndGoal == EndGoal.option_rush_hour:
        final_chapter = ChapterIndex.METRO
        chapter_list.append(ChapterIndex.FINALE)
    elif world.options.EndGoal == EndGoal.option_seal_the_deal:
        final_chapter = None
        chapter_list.append(ChapterIndex.FINALE)

    if world.is_dlc1():
        chapter_list.append(ChapterIndex.CRUISE)

    if world.is_dlc2() and final_chapter != ChapterIndex.METRO:
        chapter_list.append(ChapterIndex.METRO)

    chapter_list.remove(starting_chapter)
    world.random.shuffle(chapter_list)

    # Make sure Alpine is unlocked before any DLC chapters are, as the Alpine door needs to be open to access them
    if starting_chapter != ChapterIndex.ALPINE and (world.is_dlc1() or world.is_dlc2()):
        index1 = 69
        index2 = 69
        pos: int
        lowest_index: int
        chapter_list.remove(ChapterIndex.ALPINE)

        if world.is_dlc1():
            index1 = chapter_list.index(ChapterIndex.CRUISE)

        if world.is_dlc2() and final_chapter != ChapterIndex.METRO:
            index2 = chapter_list.index(ChapterIndex.METRO)

        lowest_index = min(index1, index2)
        if lowest_index == 0:
            pos = 0
        else:
            pos = world.random.randint(0, lowest_index)

        chapter_list.insert(pos, ChapterIndex.ALPINE)

    lowest_cost: int = world.options.LowestChapterCost.value
    highest_cost: int = world.options.HighestChapterCost.value
    cost_increment: int = world.options.ChapterCostIncrement.value
    min_difference: int = world.options.ChapterCostMinDifference.value
    last_cost = 0

    for i, chapter in enumerate(chapter_list):
        min_range: int = lowest_cost + (cost_increment * i)
        if min_range >= highest_cost:
            min_range = highest_cost-1

        value: int = world.random.randint(min_range, min(highest_cost, max(lowest_cost, last_cost + cost_increment)))
        cost = world.random.randint(value, min(value + cost_increment, highest_cost))
        if i >= 1:
            if last_cost + min_difference > cost:
                cost = last_cost + min_difference

        cost = min(cost, highest_cost)
        world.chapter_timepiece_costs[chapter] = cost
        last_cost = cost

    if final_chapter is not None:
        final_chapter_cost: int
        if world.options.FinalChapterMinCost == world.options.FinalChapterMaxCost:
            final_chapter_cost = world.options.FinalChapterMaxCost.value
        else:
            final_chapter_cost = world.random.randint(world.options.FinalChapterMinCost.value,
                                                      world.options.FinalChapterMaxCost.value)

        world.chapter_timepiece_costs[final_chapter] = final_chapter_cost

def set_rules(world: "HatInTimeWorld", rift_dict: Optional[Dict[str, Region]] = None):
    # Shuffle chapters and precalculate hat and chapter costs.
    precompute_costs(world)

    player = world.player
    brewing_hat_req = hat_requirements(world, HatType.BREWING)
    dweller_hat_req = hat_requirements(world, HatType.DWELLER)
    ice_hat_req = hat_requirements(world, HatType.ICE)

    mafia_req = Req("Time Piece", world.chapter_timepiece_costs[ChapterIndex.MAFIA])
    birds_req = Req("Time Piece", world.chapter_timepiece_costs[ChapterIndex.BIRDS])
    subcon_req = Req("Time Piece", world.chapter_timepiece_costs[ChapterIndex.SUBCON])
    alpine_req = Req("Time Piece", world.chapter_timepiece_costs[ChapterIndex.ALPINE])
    finale_req = Req("Time Piece", world.chapter_timepiece_costs[ChapterIndex.FINALE])
    metro_req = Req("Time Piece", world.chapter_timepiece_costs[ChapterIndex.METRO])
    cruise_req = Req("Time Piece", world.chapter_timepiece_costs[ChapterIndex.CRUISE])
    umbrella_req = Req("Umbrella", 1)

    add_rule(world.multiworld.get_entrance("Telescope -> Mafia Town", player),
             req_to_rule(player, mafia_req))

    add_rule(world.multiworld.get_entrance("Telescope -> Battle of the Birds", player),
             req_to_rule(player, birds_req))

    add_rule(world.multiworld.get_entrance("Telescope -> Subcon Forest", player),
             req_to_rule(player, subcon_req))

    add_rule(world.multiworld.get_entrance("Telescope -> Alpine Skyline", player),
             req_to_rule(player, alpine_req))

    add_rule(world.multiworld.get_entrance("Telescope -> Time's End", player),
             all_reqs_to_rule(player, finale_req, brewing_hat_req, dweller_hat_req))

    if world.is_dlc1():
        add_rule(world.multiworld.get_entrance("Telescope -> Arctic Cruise", player),
                 all_reqs_to_rule(player, alpine_req, cruise_req))

    if world.is_dlc2():
        add_rule(world.multiworld.get_entrance("Telescope -> Nyakuza Metro", player),
                 all_reqs_to_rule(player, alpine_req, metro_req, dweller_hat_req, ice_hat_req))

    if rift_dict:
        set_rift_rules(world, rift_dict)
    else:
        set_default_rift_rules(world)

    table = {**location_table, **event_locs}
    for (key, data) in table.items():
        if not is_location_valid(world, key):
            continue

        loc = world.multiworld.get_location(key, player)

        for hat in data.required_hats:
            hat_reqs = hat_requirements(world, hat)
            if hat_reqs:
                add_rule(loc, req_to_rule(player, hat_reqs))

        if data.hookshot:
            add_rule(loc, req_to_rule(player, HOOKSHOT_REQ))

        if data.paintings > 0 and world.options.ShuffleSubconPaintings:
            painting_req = painting_requirements(world, data.paintings)
            add_rule(loc, req_to_rule(player, painting_req))

        if data.hit_type != HitType.none and world.options.UmbrellaLogic:
            if data.hit_type == HitType.umbrella:
                add_rule(loc, req_to_rule(player, umbrella_req))

            elif data.hit_type == HitType.umbrella_or_brewing:
                add_rule(loc, any_req_to_rule(player, umbrella_req, brewing_hat_req))

            elif data.hit_type == HitType.dweller_bell:
                add_rule(loc, any_req_to_rule(player, umbrella_req, brewing_hat_req, dweller_hat_req))

        for misc in data.misc_required:
            add_rule(loc, req_to_rule(player, Req(misc, 1)))

    set_specific_rules(world)

    # Putting all of this here, so it doesn't get overridden by anything
    # Illness starts the player past the intro
    alpine_entrance = world.multiworld.get_entrance("AFR -> Alpine Skyline Area", player)
    add_rule(alpine_entrance, req_to_rule(player, HOOKSHOT_REQ))
    if world.options.UmbrellaLogic:
        add_rule(alpine_entrance, req_to_rule(player, umbrella_req))

    if zipline_logic(world):
        birdhouse_zipline = Req("Zipline Unlock - The Birdhouse Path", 1)
        lava_cake_zipline = Req("Zipline Unlock - The Lava Cake Path", 1)
        windmill_zipline = Req("Zipline Unlock - The Windmill Path", 1)
        bell_zipline = Req("Zipline Unlock - The Twilight Bell Path", 1)
        add_rule(world.multiworld.get_entrance("-> The Birdhouse", player),
                 req_to_rule(player, birdhouse_zipline))

        add_rule(world.multiworld.get_entrance("-> The Lava Cake", player),
                 req_to_rule(player, lava_cake_zipline))

        add_rule(world.multiworld.get_entrance("-> The Windmill", player),
                 req_to_rule(player, windmill_zipline))

        add_rule(world.multiworld.get_entrance("-> The Twilight Bell", player),
                 req_to_rule(player, bell_zipline))

        add_rule(world.multiworld.get_location("Act Completion (The Illness has Spread)", player),
                 all_reqs_to_rule(player, birdhouse_zipline, lava_cake_zipline, windmill_zipline))

    if zipline_logic(world):
        for (loc, zipline) in zipline_unlocks.items():
            add_rule(world.multiworld.get_location(loc, player),
                     req_to_rule(player, Req(zipline, 1)))

    dummy_entrances: List[Entrance] = []
      
    for (key, acts) in act_connections.items():
        if "Arctic Cruise" in key and not world.is_dlc1():
            continue

        entrance: Entrance = world.multiworld.get_entrance(key, player)
        region: Region = entrance.connected_region
        access_rules: List[Callable[[CollectionState], bool]] = []
        dummy_entrances.append(entrance)

        # Entrances to this act that we have to set access_rules on
        entrances: List[Entrance] = []

        for i, act in enumerate(acts, start=1):
            act_entrance: Entrance = world.multiworld.get_entrance(act, player)
            access_rules.append(act_entrance.access_rule)
            required_region = act_entrance.connected_region
            name: str = f"{key}: Connection {i}"
            new_entrance: Entrance = required_region.connect(region, name)
            entrances.append(new_entrance)

            # Copy access rules from act completions
            if "Free Roam" not in required_region.name:
                rule: Callable[[CollectionState], bool]
                name = f"Act Completion ({required_region.name})"
                rule = world.multiworld.get_location(name, player).access_rule
                access_rules.append(rule)

        for e in entrances:
            for rules in access_rules:
                add_rule(e, rules)

    for e in dummy_entrances:
        set_rule(e, RULE_ALWAYS_FALSE)

    set_event_rules(world)

    if world.options.EndGoal == EndGoal.option_finale:
        world.multiworld.completion_condition[player] = lambda state: state.has("Time Piece Cluster", player)
    elif world.options.EndGoal == EndGoal.option_rush_hour:
        world.multiworld.completion_condition[player] = lambda state: state.has("Rush Hour Cleared", player)


def set_specific_rules(world: "HatInTimeWorld"):
    add_rule(world.multiworld.get_location("Mafia Boss Shop Item", world.player),
             req_to_rule(world.player, Req("Time Piece", max(12, world.chapter_timepiece_costs[ChapterIndex.BIRDS]))))

    set_mafia_town_rules(world)
    set_botb_rules(world)
    set_subcon_rules(world)
    set_alps_rules(world)

    if world.is_dlc1():
        set_dlc1_rules(world)

    if world.is_dlc2():
        set_dlc2_rules(world)

    difficulty: Difficulty = get_difficulty(world)

    if difficulty >= Difficulty.MODERATE:
        set_moderate_rules(world)

    if difficulty >= Difficulty.HARD:
        set_hard_rules(world)

    if difficulty >= Difficulty.EXPERT:
        set_expert_rules(world)


def set_moderate_rules(world: "HatInTimeWorld"):
    player = world.player
    brewing_hat_req = hat_requirements(world, HatType.BREWING)
    dweller_hat_req = hat_requirements(world, HatType.DWELLER)
    ice_hat_req = hat_requirements(world, HatType.ICE)
    sprint_hat_req = hat_requirements(world, HatType.SPRINT)
    # Moderate: Gallery without Brewing Hat
    set_rule(world.multiworld.get_location("Act Completion (Time Rift - Gallery)", player), RULE_ALWAYS_TRUE)

    # Moderate: Above Boats via Ice Hat Sliding
    add_rule(world.multiworld.get_location("Mafia Town - Above Boats", player),
             req_to_rule(player, ice_hat_req), "or")

    # Moderate: Clock Tower Chest + Ruined Tower with nothing
    set_rule(world.multiworld.get_location("Mafia Town - Clock Tower Chest", player), RULE_ALWAYS_TRUE)
    set_rule(world.multiworld.get_location("Mafia Town - Top of Ruined Tower", player), RULE_ALWAYS_TRUE)

    # Moderate: enter and clear The Subcon Well without Hookshot and without hitting the bell
    one_painting = painting_requirements(world, 1)
    one_painting_rule = req_to_rule(player, one_painting)
    for loc in world.multiworld.get_region("The Subcon Well", player).locations:
        set_rule(loc, one_painting_rule)

    # Moderate: Vanessa Manor with nothing
    for loc in world.multiworld.get_region("Queen Vanessa's Manor", player).locations:
        set_rule(loc, one_painting_rule)

    set_rule(world.multiworld.get_location("Subcon Forest - Manor Rooftop", player),
             one_painting_rule)

    # Moderate: Village Time Rift with nothing IF umbrella logic is off
    if not world.options.UmbrellaLogic:
        set_rule(world.multiworld.get_location("Act Completion (Time Rift - Village)", player), RULE_ALWAYS_TRUE)

    # Moderate: get to Birdhouse/Yellow Band Hills without Brewing Hat
    set_rule(world.multiworld.get_entrance("-> The Birdhouse", player),
             req_to_rule(player, HOOKSHOT_REQ))
    set_rule(world.multiworld.get_location("Alpine Skyline - Yellow Band Hills", player),
             req_to_rule(player, HOOKSHOT_REQ))

    # Moderate: The Birdhouse - Dweller Platforms Relic with only Birdhouse access
    set_rule(world.multiworld.get_location("Alpine Skyline - The Birdhouse: Dweller Platforms Relic", player),
             RULE_ALWAYS_TRUE)

    # Moderate: Twilight Path without Dweller Mask
    set_rule(world.multiworld.get_location("Alpine Skyline - The Twilight Path", player), RULE_ALWAYS_TRUE)

    # Moderate: Mystifying Time Mesa time trial without hats
    set_rule(world.multiworld.get_location("Alpine Skyline - Mystifying Time Mesa: Zipline", player),
             req_to_rule(player, HOOKSHOT_REQ))

    # Moderate: Goat Refinery from TIHS with Sprint only
    add_rule(world.multiworld.get_location("Alpine Skyline - Goat Refinery", player),
             all_reqs_to_rule(player, Req("TIHS Access", 1), sprint_hat_req), "or")

    # Moderate: Finale Telescope with only Ice Hat
    add_rule(world.multiworld.get_entrance("Telescope -> Time's End", player),
             all_reqs_to_rule(player, Req("Time Piece", world.chapter_timepiece_costs[ChapterIndex.FINALE]),
                              ice_hat_req), "or")

    # Moderate: Finale without Hookshot
    set_rule(world.multiworld.get_location("Act Completion (The Finale)", player),
             req_to_rule(player, dweller_hat_req))

    if world.is_dlc1():
        # Moderate: clear Rock the Boat without Ice Hat
        set_rule(world.multiworld.get_location("Rock the Boat - Post Captain Rescue", player), RULE_ALWAYS_TRUE)
        set_rule(world.multiworld.get_location("Act Completion (Rock the Boat)", player), RULE_ALWAYS_TRUE)

        # Moderate: clear Deep Sea without Ice Hat
        set_rule(world.multiworld.get_location("Act Completion (Time Rift - Deep Sea)", player),
                 all_reqs_to_rule(player, HOOKSHOT_REQ, dweller_hat_req))

    # There is a glitched fall damage volume near the Yellow Overpass time piece that warps the player to Pink Paw.
    # Yellow Overpass time piece can also be reached without Hookshot quite easily.
    if world.is_dlc2():
        # No Hookshot
        set_rule(world.multiworld.get_location("Act Completion (Yellow Overpass Station)", player),
                 RULE_ALWAYS_TRUE)

        # No Dweller, Hookshot, or Time Stop for these
        set_rule(world.multiworld.get_location("Pink Paw Station - Cat Vacuum", player), RULE_ALWAYS_TRUE)
        set_rule(world.multiworld.get_location("Pink Paw Station - Behind Fan", player), RULE_ALWAYS_TRUE)
        set_rule(world.multiworld.get_location("Pink Paw Station - Pink Ticket Booth", player), RULE_ALWAYS_TRUE)
        set_rule(world.multiworld.get_location("Act Completion (Pink Paw Station)", player), RULE_ALWAYS_TRUE)
        for key in shop_locations.keys():
            if "Pink Paw Station Thug" in key and is_location_valid(world, key):
                set_rule(world.multiworld.get_location(key, player), RULE_ALWAYS_TRUE)

        # Moderate: clear Rush Hour without Hookshot
        set_rule(world.multiworld.get_location("Act Completion (Rush Hour)", player),
                 all_reqs_to_rule(player,
                                  Req("Metro Ticket - Pink", 1),
                                  Req("Metro Ticket - Yellow", 1),
                                  Req("Metro Ticket - Blue", 1),
                                  ice_hat_req,
                                  brewing_hat_req))

        # Moderate: Bluefin Tunnel + Pink Paw Station without tickets
        if not world.options.NoTicketSkips:
            set_rule(world.multiworld.get_entrance("-> Pink Paw Station", player), RULE_ALWAYS_TRUE)
            set_rule(world.multiworld.get_entrance("-> Bluefin Tunnel", player), RULE_ALWAYS_TRUE)


def set_hard_rules(world: "HatInTimeWorld"):
    player = world.player
    brewing_hat_req = hat_requirements(world, HatType.BREWING)
    ice_hat_req = hat_requirements(world, HatType.ICE)
    sprint_hat_req = hat_requirements(world, HatType.SPRINT)
    # Hard: clear Time Rift - The Twilight Bell with Sprint+Scooter only
    add_rule(world.multiworld.get_location("Act Completion (Time Rift - The Twilight Bell)", player),
             all_reqs_to_rule(player, sprint_hat_req, Req("Scooter Badge", 1)), "or")

    # No Dweller Mask required
    paintings_3 = painting_requirements(world, 3, True)
    paintings_2 = painting_requirements(world, 2, True)
    paintings_1 = painting_requirements(world, 1, False)
    set_rule(world.multiworld.get_location("Subcon Forest - Dweller Floating Rocks", player),
             req_to_rule(player, paintings_3))
    set_rule(world.multiworld.get_location("Subcon Forest - Dweller Platforming Tree B", player),
             req_to_rule(player, paintings_3))

    # Cherry bridge over boss arena gap (painting still expected)
    set_rule(world.multiworld.get_location("Subcon Forest - Boss Arena Chest", player),
             any_req_to_rule(player, paintings_1, Req("YCHE Access", 1)))

    set_rule(world.multiworld.get_location("Subcon Forest - Noose Treehouse", player),
             req_to_rule(player, paintings_2))
    set_rule(world.multiworld.get_location("Subcon Forest - Long Tree Climb Chest", player),
             req_to_rule(player, paintings_2))
    set_rule(world.multiworld.get_location("Subcon Forest - Tall Tree Hookshot Swing", player),
             req_to_rule(player, paintings_3))

    # SDJ
    add_rule(world.multiworld.get_location("Subcon Forest - Long Tree Climb Chest", player),
             all_reqs_to_rule(player, sprint_hat_req, paintings_2), "or")

    add_rule(world.multiworld.get_location("Act Completion (Time Rift - Curly Tail Trail)", player),
             req_to_rule(player, sprint_hat_req), "or")

    # Hard: Goat Refinery from TIHS with nothing
    add_rule(world.multiworld.get_location("Alpine Skyline - Goat Refinery", player),
             lambda state: state.has("TIHS Access", player), "or")

    if world.is_dlc1():
        # Hard: clear Deep Sea without Dweller Mask
        set_rule(world.multiworld.get_location("Act Completion (Time Rift - Deep Sea)", player),
                 req_to_rule(player, HOOKSHOT_REQ))

    if world.is_dlc2():
        # Hard: clear Green Clean Manhole without Dweller Mask
        set_rule(world.multiworld.get_location("Act Completion (Green Clean Manhole)", player),
                 req_to_rule(player, ice_hat_req))

        # Hard: clear Rush Hour with Brewing Hat only
        if world.options.NoTicketSkips != NoTicketSkips.option_true:
            set_rule(world.multiworld.get_location("Act Completion (Rush Hour)", player),
                     req_to_rule(player, brewing_hat_req))
        else:
            set_rule(world.multiworld.get_location("Act Completion (Rush Hour)", player),
                     all_reqs_to_rule(player, brewing_hat_req,
                                      Req("Metro Ticket - Yellow", 1),
                                      Req("Metro Ticket - Blue", 1),
                                      Req("Metro Ticket - Pink", 1)))


def set_expert_rules(world: "HatInTimeWorld"):
    player = world.player
    brewing_hat_req = hat_requirements(world, HatType.BREWING)
    dweller_hat_req = hat_requirements(world, HatType.DWELLER)
    sprint_hat_req = hat_requirements(world, HatType.SPRINT)
    time_stop_hat_req = hat_requirements(world, HatType.TIME_STOP)
    # Finale Telescope with no hats
    set_rule(world.multiworld.get_entrance("Telescope -> Time's End", player),
             req_to_rule(player, Req("Time Piece", world.chapter_timepiece_costs[ChapterIndex.FINALE])))

    # Expert: Mafia Town - Above Boats, Top of Lighthouse, and Hot Air Balloon with nothing
    set_rule(world.multiworld.get_location("Mafia Town - Above Boats", player), RULE_ALWAYS_TRUE)
    set_rule(world.multiworld.get_location("Mafia Town - Top of Lighthouse", player), RULE_ALWAYS_TRUE)
    set_rule(world.multiworld.get_location("Mafia Town - Hot Air Balloon", player), RULE_ALWAYS_TRUE)

    # Expert: Clear Dead Bird Studio with nothing
    for loc in world.multiworld.get_region("Dead Bird Studio - Post Elevator Area", player).locations:
        set_rule(loc, RULE_ALWAYS_TRUE)

    set_rule(world.multiworld.get_location("Act Completion (Dead Bird Studio)", player), RULE_ALWAYS_TRUE)

    # Expert: Clear Dead Bird Studio Basement without Hookshot
    for loc in world.multiworld.get_region("Dead Bird Studio Basement", player).locations:
        set_rule(loc, RULE_ALWAYS_TRUE)

    # Expert: get to and clear Twilight Bell without Dweller Mask.
    # Dweller Mask OR Sprint Hat OR Brewing Hat OR Time Stop + Umbrella required to complete act.
    add_rule(world.multiworld.get_entrance("-> The Twilight Bell", player),
             req_to_rule(player, HOOKSHOT_REQ), "or")

    add_rule(world.multiworld.get_location("Act Completion (The Twilight Bell)", player),
             # brewing hat, dweller hat, sprint hat, or (time stop and umbrella)
             complex_reqs_to_rule(player, AnyReq([
                 brewing_hat_req,
                 dweller_hat_req,
                 sprint_hat_req,
                 AllReq([time_stop_hat_req, Req("Umbrella", 1)]),
             ])))

    # Expert: Time Rift - Curly Tail Trail with nothing
    # Time Rift - Twilight Bell and Time Rift - Village with nothing
    set_rule(world.multiworld.get_location("Act Completion (Time Rift - Curly Tail Trail)", player),
             RULE_ALWAYS_TRUE)

    set_rule(world.multiworld.get_location("Act Completion (Time Rift - Village)", player), RULE_ALWAYS_TRUE)
    set_rule(world.multiworld.get_location("Act Completion (Time Rift - The Twilight Bell)", player),
             RULE_ALWAYS_TRUE)

    # Expert: Cherry Hovering
    subcon_area = world.multiworld.get_region("Subcon Forest Area", player)
    yche = world.multiworld.get_region("Your Contract has Expired", player)
    entrance = yche.connect(subcon_area, "Subcon Forest Entrance YCHE")

    paintings_1 = painting_requirements(world, 1, True)
    paintings_3 = painting_requirements(world, 3, True)
    if world.options.NoPaintingSkips:
        add_rule(entrance, req_to_rule(player, paintings_1))

    set_rule(world.multiworld.get_location("Act Completion (Toilet of Doom)", player),
             complex_reqs_to_rule(player, AllReq([
                 HOOKSHOT_REQ,
                 hit_requirements(world),
                 paintings_1,
             ])))

    # Set painting rules only. Skipping paintings is determined in has_paintings
    set_rule(world.multiworld.get_location("Subcon Forest - Boss Arena Chest", player),
             req_to_rule(player, paintings_1))
    set_rule(world.multiworld.get_location("Subcon Forest - Magnet Badge Bush", player),
             req_to_rule(player, paintings_3))

    # You can cherry hover to Snatcher's post-fight cutscene, which completes the level without having to fight him
    subcon_area.connect(yche, "Snatcher Hover")
    set_rule(world.multiworld.get_location("Act Completion (Your Contract has Expired)", player),
             RULE_ALWAYS_TRUE)

    if world.is_dlc2():
        # Expert: clear Rush Hour with nothing
        if not world.options.NoTicketSkips:
            set_rule(world.multiworld.get_location("Act Completion (Rush Hour)", player), RULE_ALWAYS_TRUE)
        else:
            blue_ticket = Req("Metro Ticket - Blue", 1)
            yellow_ticket = Req("Metro Ticket - Yellow", 1)
            pink_ticket = Req("Metro Ticket - Pink", 1)
            set_rule(world.multiworld.get_location("Act Completion (Rush Hour)", player),
                     all_reqs_to_rule(player, yellow_ticket, blue_ticket, pink_ticket))

        # Expert: Yellow/Green Manhole with nothing using a Boop Clip
        set_rule(world.multiworld.get_location("Act Completion (Yellow Overpass Manhole)", player),
                 RULE_ALWAYS_TRUE)
        set_rule(world.multiworld.get_location("Act Completion (Green Clean Manhole)", player),
                 RULE_ALWAYS_TRUE)


def set_mafia_town_rules(world: "HatInTimeWorld"):
    player = world.player
    sprint_hat_req = hat_requirements(world, HatType.SPRINT)
    add_rule(world.multiworld.get_location("Mafia Town - Behind HQ Chest", player),
             lambda state: state.can_reach("Act Completion (Heating Up Mafia Town)", "Location", player)
             or state.can_reach("Down with the Mafia!", "Region", player)
             or state.can_reach("Cheating the Race", "Region", player)
             or state.can_reach("The Golden Vault", "Region", player))

    # Old guys don't appear in SCFOS
    add_rule(world.multiworld.get_location("Mafia Town - Old Man (Steel Beams)", player),
             lambda state: state.can_reach("Welcome to Mafia Town", "Region", player)
             or state.can_reach("Barrel Battle", "Region", player)
             or state.can_reach("Cheating the Race", "Region", player)
             or state.can_reach("The Golden Vault", "Region", player)
             or state.can_reach("Down with the Mafia!", "Region", player))

    add_rule(world.multiworld.get_location("Mafia Town - Old Man (Seaside Spaghetti)", player),
             lambda state: state.can_reach("Welcome to Mafia Town", "Region", player)
             or state.can_reach("Barrel Battle", "Region", player)
             or state.can_reach("Cheating the Race", "Region", player)
             or state.can_reach("The Golden Vault", "Region", player)
             or state.can_reach("Down with the Mafia!", "Region", player))

    # Only available outside She Came from Outer Space
    add_rule(world.multiworld.get_location("Mafia Town - Mafia Geek Platform", player),
             lambda state: state.can_reach("Welcome to Mafia Town", "Region", player)
             or state.can_reach("Barrel Battle", "Region", player)
             or state.can_reach("Down with the Mafia!", "Region", player)
             or state.can_reach("Cheating the Race", "Region", player)
             or state.can_reach("Heating Up Mafia Town", "Region", player)
             or state.can_reach("The Golden Vault", "Region", player))

    # Only available outside Down with the Mafia! (for some reason)
    add_rule(world.multiworld.get_location("Mafia Town - On Scaffolding", player),
             lambda state: state.can_reach("Welcome to Mafia Town", "Region", player)
             or state.can_reach("Barrel Battle", "Region", player)
             or state.can_reach("She Came from Outer Space", "Region", player)
             or state.can_reach("Cheating the Race", "Region", player)
             or state.can_reach("Heating Up Mafia Town", "Region", player)
             or state.can_reach("The Golden Vault", "Region", player))

    # For some reason, the brewing crate is removed in HUMT
    humt_req = Req("HUMT Access", 1)
    add_rule(world.multiworld.get_location("Mafia Town - Secret Cave", player),
             req_to_rule(player, humt_req), "or")

    # Can bounce across the lava to get this without Hookshot (need to die though)
    add_rule(world.multiworld.get_location("Mafia Town - Above Boats", player),
             req_to_rule(player, humt_req), "or")

    if world.options.CTRLogic == CTRLogic.option_nothing:
        set_rule(world.multiworld.get_location("Act Completion (Cheating the Race)", player), RULE_ALWAYS_TRUE)
    elif world.options.CTRLogic == CTRLogic.option_sprint:
        add_rule(world.multiworld.get_location("Act Completion (Cheating the Race)", player),
                 req_to_rule(player, sprint_hat_req), "or")
    elif world.options.CTRLogic == CTRLogic.option_scooter:
        add_rule(world.multiworld.get_location("Act Completion (Cheating the Race)", player),
                 all_reqs_to_rule(player, sprint_hat_req, Req("Scooter Badge", 1)), "or")


def set_botb_rules(world: "HatInTimeWorld"):
    player = world.player
    brewing_hat_req = hat_requirements(world, HatType.BREWING)
    umbrella_req = Req("Umbrella", 1)
    if not world.options.UmbrellaLogic and get_difficulty(world) < Difficulty.MODERATE:
        set_rule(world.multiworld.get_location("Dead Bird Studio - DJ Grooves Sign Chest", player),
                 any_req_to_rule(player, umbrella_req, brewing_hat_req))
        set_rule(world.multiworld.get_location("Dead Bird Studio - Tepee Chest", player),
                 any_req_to_rule(player, umbrella_req, brewing_hat_req))
        set_rule(world.multiworld.get_location("Dead Bird Studio - Conductor Chest", player),
                 any_req_to_rule(player, umbrella_req, brewing_hat_req))
        set_rule(world.multiworld.get_location("Act Completion (Dead Bird Studio)", player),
                 any_req_to_rule(player, umbrella_req, brewing_hat_req))


def set_subcon_rules(world: "HatInTimeWorld"):
    player = world.player
    brewing_hat_req = hat_requirements(world, HatType.BREWING)
    dweller_hat_req = hat_requirements(world, HatType.DWELLER)
    umbrella_req = Req("Umbrella", 1)
    set_rule(world.multiworld.get_location("Act Completion (Time Rift - Village)", player),
             any_req_to_rule(player, brewing_hat_req, umbrella_req, dweller_hat_req))

    # You can't skip over the boss arena wall without cherry hover, so these two need to be set this way
    painting_noskip = painting_requirements(world, 1, False)
    set_rule(world.multiworld.get_location("Subcon Forest - Boss Arena Chest", player),
             complex_reqs_to_rule(player, AnyReq([
                 AllReq([
                     Req("TOD Access", 1),
                     HOOKSHOT_REQ,
                     painting_noskip,
                 ]),
                 Req("YCHE Access", 1),
             ])))

    # The painting wall can't be skipped without cherry hover, which is Expert
    set_rule(world.multiworld.get_location("Act Completion (Toilet of Doom)", player),
             complex_reqs_to_rule(player, AllReq([
                 HOOKSHOT_REQ,
                 hit_requirements(world),
                 painting_noskip,
             ])))

    add_rule(world.multiworld.get_entrance("Subcon Forest - Act 2", player),
             lambda state: state.has("Snatcher's Contract - The Subcon Well", player))

    add_rule(world.multiworld.get_entrance("Subcon Forest - Act 3", player),
             lambda state: state.has("Snatcher's Contract - Toilet of Doom", player))

    add_rule(world.multiworld.get_entrance("Subcon Forest - Act 4", player),
             lambda state: state.has("Snatcher's Contract - Queen Vanessa's Manor", player))

    add_rule(world.multiworld.get_entrance("Subcon Forest - Act 5", player),
             lambda state: state.has("Snatcher's Contract - Mail Delivery Service", player))

    if painting_logic(world):
        add_rule(world.multiworld.get_location("Act Completion (Contractual Obligations)", player),
                 req_to_rule(player, painting_noskip))


def set_alps_rules(world: "HatInTimeWorld"):
    player = world.player
    brewing_hat_req = hat_requirements(world, HatType.BREWING)
    dweller_hat_req = hat_requirements(world, HatType.DWELLER)
    sprint_hat_req = hat_requirements(world, HatType.SPRINT)
    time_stop_hat_req = hat_requirements(world, HatType.TIME_STOP)
    add_rule(world.multiworld.get_entrance("-> The Birdhouse", player),
             all_reqs_to_rule(player, HOOKSHOT_REQ, brewing_hat_req))

    add_rule(world.multiworld.get_entrance("-> The Lava Cake", player),
             req_to_rule(player, HOOKSHOT_REQ))

    add_rule(world.multiworld.get_entrance("-> The Windmill", player),
             req_to_rule(player, HOOKSHOT_REQ))

    add_rule(world.multiworld.get_entrance("-> The Twilight Bell", player),
             all_reqs_to_rule(player, HOOKSHOT_REQ, dweller_hat_req))

    add_rule(world.multiworld.get_location("Alpine Skyline - Mystifying Time Mesa: Zipline", player),
             any_req_to_rule(player, sprint_hat_req, time_stop_hat_req))

    add_rule(world.multiworld.get_entrance("Alpine Skyline - Finale", player),
             lambda state: can_clear_alpine(state, player))

    add_rule(world.multiworld.get_location("Alpine Skyline - Goat Refinery", player),
             complex_reqs_to_rule(player, AllReq([
                 Req("AFR Access", 1),
                 HOOKSHOT_REQ,
                 hit_requirements(world, True),
             ])))


def set_dlc1_rules(world: "HatInTimeWorld"):
    player = world.player
    add_rule(world.multiworld.get_entrance("Cruise Ship Entrance BV", player),
             req_to_rule(player, HOOKSHOT_REQ))

    # This particular item isn't present in Act 3 for some reason, yes in vanilla too
    add_rule(world.multiworld.get_location("The Arctic Cruise - Toilet", player),
             lambda state: state.can_reach("Bon Voyage!", "Region", player)
             or state.can_reach("Ship Shape", "Region", player))


def set_dlc2_rules(world: "HatInTimeWorld"):
    player = world.player
    green_ticket = Req("Metro Ticket - Green", 1)
    blue_ticket = Req("Metro Ticket - Blue", 1)
    yellow_ticket = Req("Metro Ticket - Yellow", 1)
    pink_ticket = Req("Metro Ticket - Pink", 1)
    add_rule(world.multiworld.get_entrance("-> Bluefin Tunnel", player),
             any_req_to_rule(player, green_ticket, blue_ticket))

    add_rule(world.multiworld.get_entrance("-> Pink Paw Station", player),
             complex_reqs_to_rule(player, AnyReq([
                 pink_ticket,
                 AllReq([yellow_ticket, blue_ticket]),
             ])))

    add_rule(world.multiworld.get_entrance("Nyakuza Metro - Finale", player),
             lambda state: can_clear_metro(state, player))

    add_rule(world.multiworld.get_location("Act Completion (Rush Hour)", player),
             all_reqs_to_rule(player, yellow_ticket, blue_ticket, pink_ticket))

    for key in shop_locations.keys():
        if "Green Clean Station Thug B" in key and is_location_valid(world, key):
            add_rule(world.multiworld.get_location(key, player),
                     req_to_rule(player, yellow_ticket), "or")


def reg_act_connection(world: "HatInTimeWorld", region: Union[str, Region], unlocked_entrance: Union[str, Entrance]):
    reg: Region
    entrance: Entrance
    if isinstance(region, str):
        reg = world.multiworld.get_region(region, world.player)
    else:
        reg = region

    if isinstance(unlocked_entrance, str):
        entrance = world.multiworld.get_entrance(unlocked_entrance, world.player)
    else:
        entrance = unlocked_entrance

    world.multiworld.register_indirect_condition(reg, entrance)


# See randomize_act_entrances in Regions.py
def set_rift_rules(world: "HatInTimeWorld", regions: Dict[str, Region]):
    player = world.player
    brewing_hat_req = hat_requirements(world, HatType.BREWING)
    dweller_hat_req = hat_requirements(world, HatType.DWELLER)
    birds_req = Req("Time Piece", world.chapter_timepiece_costs[ChapterIndex.BIRDS])
    alpine_req = Req("Time Piece", world.chapter_timepiece_costs[ChapterIndex.ALPINE])

    # This is accessing the regions in place of these time rifts, so we can set the rules on all the entrances.
    for entrance in regions["Time Rift - Gallery"].entrances:
        add_rule(entrance, all_reqs_to_rule(player, brewing_hat_req, birds_req))

    for entrance in regions["Time Rift - The Lab"].entrances:
        add_rule(entrance, all_reqs_to_rule(player, dweller_hat_req, alpine_req))

    for entrance in regions["Time Rift - Sewers"].entrances:
        add_rule(entrance, lambda state: can_clear_required_act(state, world, "Mafia Town - Act 4"))
        reg_act_connection(world, world.multiworld.get_entrance("Mafia Town - Act 4",
                                                                player).connected_region, entrance)

    for entrance in regions["Time Rift - Bazaar"].entrances:
        add_rule(entrance, lambda state: can_clear_required_act(state, world, "Mafia Town - Act 6"))
        reg_act_connection(world, world.multiworld.get_entrance("Mafia Town - Act 6",
                                                                player).connected_region, entrance)

    for entrance in regions["Time Rift - Mafia of Cooks"].entrances:
        add_rule(entrance, all_reqs_to_rule(player, *relic_combo_requirements(world, "Burger")))

    for entrance in regions["Time Rift - The Owl Express"].entrances:
        add_rule(entrance, lambda state: can_clear_required_act(state, world, "Battle of the Birds - Act 2"))
        add_rule(entrance, lambda state: can_clear_required_act(state, world, "Battle of the Birds - Act 3"))
        reg_act_connection(world, world.multiworld.get_entrance("Battle of the Birds - Act 2",
                                                                player).connected_region, entrance)
        reg_act_connection(world, world.multiworld.get_entrance("Battle of the Birds - Act 3",
                                                                player).connected_region, entrance)

    for entrance in regions["Time Rift - The Moon"].entrances:
        add_rule(entrance, lambda state: can_clear_required_act(state, world, "Battle of the Birds - Act 4"))
        add_rule(entrance, lambda state: can_clear_required_act(state, world, "Battle of the Birds - Act 5"))
        reg_act_connection(world, world.multiworld.get_entrance("Battle of the Birds - Act 4",
                                                                player).connected_region, entrance)
        reg_act_connection(world, world.multiworld.get_entrance("Battle of the Birds - Act 5",
                                                                player).connected_region, entrance)

    for entrance in regions["Time Rift - Dead Bird Studio"].entrances:
        add_rule(entrance, all_reqs_to_rule(player, *relic_combo_requirements(world, "Train")))

    paintings_2 = painting_requirements(world, 2)
    paintings_3 = painting_requirements(world, 3)
    for entrance in regions["Time Rift - Pipe"].entrances:
        add_rule(entrance, lambda state: can_clear_required_act(state, world, "Subcon Forest - Act 2"))
        reg_act_connection(world, world.multiworld.get_entrance("Subcon Forest - Act 2",
                                                                player).connected_region, entrance)
        if painting_logic(world):
            add_rule(entrance, req_to_rule(player, paintings_2))

    for entrance in regions["Time Rift - Village"].entrances:
        add_rule(entrance, lambda state: can_clear_required_act(state, world, "Subcon Forest - Act 4"))
        reg_act_connection(world, world.multiworld.get_entrance("Subcon Forest - Act 4",
                                                                player).connected_region, entrance)

        if painting_logic(world):
            add_rule(entrance, req_to_rule(player, paintings_2))

    for entrance in regions["Time Rift - Sleepy Subcon"].entrances:
        add_rule(entrance, all_reqs_to_rule(player, *relic_combo_requirements(world, "UFO")))
        if painting_logic(world):
            add_rule(entrance, req_to_rule(player, paintings_3))

    windmill_req = Req("Windmill Cleared", 1)
    for entrance in regions["Time Rift - Curly Tail Trail"].entrances:
        add_rule(entrance, req_to_rule(player, windmill_req))

    bell_req = Req("Twilight Bell Cleared", 1)
    for entrance in regions["Time Rift - The Twilight Bell"].entrances:
        add_rule(entrance, req_to_rule(player, bell_req))

    for entrance in regions["Time Rift - Alpine Skyline"].entrances:
        add_rule(entrance, all_reqs_to_rule(player, *relic_combo_requirements(world, "Crayon")))
        if entrance.parent_region.name == "Alpine Free Roam":
            add_rule(entrance, complex_reqs_to_rule(player, AllReq([
                HOOKSHOT_REQ,
                hit_requirements(world, umbrella_only=True),
            ])))

    if world.is_dlc1():
        for entrance in regions["Time Rift - Balcony"].entrances:
            add_rule(entrance, lambda state: can_clear_required_act(state, world, "The Arctic Cruise - Finale"))
            reg_act_connection(world, world.multiworld.get_entrance("The Arctic Cruise - Finale",
                                                                    player).connected_region, entrance)

        for entrance in regions["Time Rift - Deep Sea"].entrances:
            add_rule(entrance, all_reqs_to_rule(player, *relic_combo_requirements(world, "Cake")))

    if world.is_dlc2():
        for entrance in regions["Time Rift - Rumbi Factory"].entrances:
            add_rule(entrance, all_reqs_to_rule(player, *relic_combo_requirements(world, "Necklace")))


# Basically the same as above, but without the need of the dict since we are just setting defaults
# Called if Act Rando is disabled
def set_default_rift_rules(world: "HatInTimeWorld"):
    player = world.player
    brewing_hat_req = hat_requirements(world, HatType.BREWING)
    dweller_hat_req = hat_requirements(world, HatType.DWELLER)
    birds_req = Req("Time Piece", world.chapter_timepiece_costs[ChapterIndex.BIRDS])
    alpine_req = Req("Time Piece", world.chapter_timepiece_costs[ChapterIndex.ALPINE])

    for entrance in world.multiworld.get_region("Time Rift - Gallery", player).entrances:
        add_rule(entrance, all_reqs_to_rule(player, brewing_hat_req, birds_req))

    for entrance in world.multiworld.get_region("Time Rift - The Lab", player).entrances:
        add_rule(entrance, all_reqs_to_rule(player, dweller_hat_req, alpine_req))

    for entrance in world.multiworld.get_region("Time Rift - Sewers", player).entrances:
        add_rule(entrance, lambda state: can_clear_required_act(state, world, "Mafia Town - Act 4"))
        reg_act_connection(world, "Down with the Mafia!", entrance.name)

    for entrance in world.multiworld.get_region("Time Rift - Bazaar", player).entrances:
        add_rule(entrance, lambda state: can_clear_required_act(state, world, "Mafia Town - Act 6"))
        reg_act_connection(world, "Heating Up Mafia Town", entrance.name)

    for entrance in world.multiworld.get_region("Time Rift - Mafia of Cooks", player).entrances:
        add_rule(entrance, all_reqs_to_rule(player, *relic_combo_requirements(world, "Burger")))

    for entrance in world.multiworld.get_region("Time Rift - The Owl Express", player).entrances:
        add_rule(entrance, lambda state: can_clear_required_act(state, world, "Battle of the Birds - Act 2"))
        add_rule(entrance, lambda state: can_clear_required_act(state, world, "Battle of the Birds - Act 3"))
        reg_act_connection(world, "Murder on the Owl Express", entrance.name)
        reg_act_connection(world, "Picture Perfect", entrance.name)

    for entrance in world.multiworld.get_region("Time Rift - The Moon", player).entrances:
        add_rule(entrance, lambda state: can_clear_required_act(state, world, "Battle of the Birds - Act 4"))
        add_rule(entrance, lambda state: can_clear_required_act(state, world, "Battle of the Birds - Act 5"))
        reg_act_connection(world, "Train Rush", entrance.name)
        reg_act_connection(world, "The Big Parade", entrance.name)

    for entrance in world.multiworld.get_region("Time Rift - Dead Bird Studio", player).entrances:
        add_rule(entrance, all_reqs_to_rule(player, *relic_combo_requirements(world, "Train")))

    paintings_2 = painting_requirements(world, 2)
    paintings_3 = painting_requirements(world, 3)
    for entrance in world.multiworld.get_region("Time Rift - Pipe", player).entrances:
        add_rule(entrance, lambda state: can_clear_required_act(state, world, "Subcon Forest - Act 2"))
        reg_act_connection(world, "The Subcon Well", entrance.name)
        if painting_logic(world):
            add_rule(entrance, req_to_rule(player, paintings_2))

    for entrance in world.multiworld.get_region("Time Rift - Village", player).entrances:
        add_rule(entrance, lambda state: can_clear_required_act(state, world, "Subcon Forest - Act 4"))
        reg_act_connection(world, "Queen Vanessa's Manor", entrance.name)
        if painting_logic(world):
            add_rule(entrance, req_to_rule(player, paintings_2))

    for entrance in world.multiworld.get_region("Time Rift - Sleepy Subcon", player).entrances:
        add_rule(entrance, all_reqs_to_rule(player, *relic_combo_requirements(world, "UFO")))
        if painting_logic(world):
            add_rule(entrance, req_to_rule(player, paintings_3))

    windmill_req = Req("Windmill Cleared", 1)
    for entrance in world.multiworld.get_region("Time Rift - Curly Tail Trail", player).entrances:
        add_rule(entrance, req_to_rule(player, windmill_req))

    bell_req = Req("Twilight Bell Cleared", 1)
    for entrance in world.multiworld.get_region("Time Rift - The Twilight Bell", player).entrances:
        add_rule(entrance, req_to_rule(player, bell_req))

    for entrance in world.multiworld.get_region("Time Rift - Alpine Skyline", player).entrances:
        add_rule(entrance, all_reqs_to_rule(player, *relic_combo_requirements(world, "Crayon")))
        if entrance.parent_region.name == "Alpine Free Roam":
            add_rule(entrance, complex_reqs_to_rule(player, AllReq([
                HOOKSHOT_REQ,
                hit_requirements(world, umbrella_only=True),
            ])))

    if world.is_dlc1():
        for entrance in world.multiworld.get_region("Time Rift - Balcony", player).entrances:
            add_rule(entrance, lambda state: can_clear_required_act(state, world, "The Arctic Cruise - Finale"))
            reg_act_connection(world, "Rock the Boat", entrance.name)

        for entrance in world.multiworld.get_region("Time Rift - Deep Sea", player).entrances:
            add_rule(entrance, all_reqs_to_rule(player, *relic_combo_requirements(world, "Cake")))

    if world.is_dlc2():
        for entrance in world.multiworld.get_region("Time Rift - Rumbi Factory", player).entrances:
            add_rule(entrance, all_reqs_to_rule(player, *relic_combo_requirements(world, "Necklace")))


def set_event_rules(world: "HatInTimeWorld"):
    for (name, data) in event_locs.items():
        if not is_location_valid(world, name):
            continue

        event: Location = world.multiworld.get_location(name, world.player)

        if data.act_event:
            add_rule(event, world.multiworld.get_location(f"Act Completion ({data.region})", world.player).access_rule)
