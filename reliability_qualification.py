"""Live release gates for the sign-in/recovery reliability candidate."""
CHECKS = {
    'us_ten_consecutive_signins': ('Repeat US sign-in', 'Complete ten consecutive US sign-ins. Record each result and any timeout or retry.'),
    'steam_ten_consecutive_signins': ('Repeat Steam sign-in', 'With the Mac Steam client online, complete ten consecutive Steam-provider sign-ins. Record each result.'),
    'us_relaunch_and_recovery': ('Recover and relaunch a US session', 'Cancel a US sign-in, retry manually, close the game and relaunch. Confirm recovery without changing another installation.'),
    'steam_relaunch_and_recovery': ('Recover and relaunch a Steam session', 'Cancel a Steam-provider sign-in, retry manually and relaunch after closing the game. Confirm Steam and launcher recovery.'),
    'character_selection': ('Choose a character', 'Select a character and enter the world successfully.'),
    'objects_and_textures': ('Inspect objects and textures', 'Inspect world objects, clothing, text and effects. Record missing models, red surfaces or corrupted textures.'),
    'movement': ('Move through the world', 'Walk, turn the camera and change zones. Confirm controls and rendering remain usable.'),
    'combat': ('Complete combat', 'Enter and complete combat. Check visible participants, spell effects, targeting and input.'),
    'audio': ('Hear game audio', 'Check music, effects and audio during gameplay.'),
    'cursor': ('Check the larger cursor', 'Check cursor size, appearance and click position in menus and gameplay.'),
    'ten_minutes_gameplay': ('Play for ten minutes', 'Continue normal movement, zone changes and combat for at least ten minutes. Record interruptions or rendering failures.'),
    'fullscreen_ten_app_switches': ('Switch apps while fullscreen', 'In fullscreen, switch away and back ten times. Check rendering, input and continued gameplay after each return.'),
    'windowed_ten_app_switches': ('Switch apps while windowed', 'In windowed mode, switch away and back ten times. Check rendering, input and continued gameplay after each return.'),
    'fresh_streamed_vs_existing_same_character_area_settings': ('Compare fresh and existing content', 'Use separate fresh and existing installations with the same character, area and graphics settings. Compare streamed content, models and textures.'),
    'settings_60fps_legacy_pacing_preserved': ('Preserve graphics and pacing settings', 'Confirm resolution, graphics settings, the 60 FPS option, larger cursor and legacy pacing remain as selected.'),
    'recovery_other_wine_installations_untouched': ('Limit recovery to this game', 'Use Force Quit Game for a stuck standalone session. Confirm other Wine games and installations remain running and unchanged.'),
    'updates_block_recovery': ('Keep recovery safe during updates', 'During an update or prepared-file installation, verify that game recovery cannot interrupt replacement of installed content. Cancel safely before retrying.'),
    'classic_mode_scenery': ('Inspect classic-mode scenery', 'In classic mode, inspect streets, interiors, floors and world objects. Record missing or corrupted scenery.'),
    'regular_mode_scenery': ('Inspect regular-mode scenery', 'Repeat scenery checks in regular mode with the same character and graphics settings.'),
    'inventory_clothing_and_mounts': ('Inspect clothing and mounts', 'Open inventory and inspect equipped clothing, previews and mounts. Confirm their models and textures are visible.'),
    'bartleby_and_floor_textures': ('Inspect Bartleby and floors', 'Visit Bartleby and nearby areas. Check Bartleby, ground and floor textures for missing or red surfaces.'),
    'arcanum_paradox_visible_combatants': ('Inspect Arcanum Paradox combat', 'Enter Arcanum Paradox combat and confirm all combatants, targeting and effects are visible.'),
    'visual_preload_fresh_imported_restart': ('Prepare visuals and restart', 'Complete full visual preload on separate fresh and imported installations, restart the launcher and confirm verified content is reused.'),
    'visual_preload_gui_cancel_resume': ('Cancel and resume visual preparation', 'Cancel visual preload from the launcher, reopen it and retry. Confirm accepted partial downloads resume and existing content remains usable.'),
    'uncapped_and_60fps_choice_preserved': ('Keep the frame-rate choice', 'Select uncapped and 60 FPS in turn, restart and confirm each selection persists and remains available.'),
}
GATES = list(CHECKS)


def validate(evidence, components):
    if evidence.get('components') != components:
        raise ValueError('Reliability evidence must match the final app components exactly')
    missing = [gate for gate in GATES if evidence.get('gates', {}).get(gate) is not True]
    if missing:
        raise ValueError('Unverified reliability gates: ' + ', '.join(missing))
    for gate in GATES:
        observation = evidence.get('observations', {}).get(gate)
        if not isinstance(observation, str) or not observation.strip():
            raise ValueError('Reliability gates require a live observation: ' + gate)
