"""Exercise list refreshes with Textual's real event and scrolling behavior."""

import asyncio
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from python.frontend.core_types import ConfigItem
from python.frontend.ui import ConfigOptionList, ConfirmDialog, DuskyTUI
from textual.widgets import Markdown, Tabs
from textual.events import MouseScrollDown


class FakeEngine:
    target_path = ""

    def load_state(self):
        return {}


class NetworkUiTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_keeps_mouse_scrolling_and_logical_selection(self):
        key = ("fixture", "")
        items = [
            ConfigItem(label=f"Item {i}", key=f"item{i}", type_="bool", default=False, group="Items")
            for i in range(30)
        ]
        app = DuskyTUI(
            engine_pool={key: FakeEngine()}, default_engine_key=key,
            schema={0: items}, tabs=["Devices"], enable_user_presets=False,
        )
        async with app.run_test(size=(80, 18)) as pilot:
            await pilot.pause()
            options = app.query_one("#list-0", ConfigOptionList)
            options.scroll_y = 15
            await pilot.pause()
            app._refresh_all_ui()
            await pilot.pause()
            self.assertEqual(options.scroll_y, 15)
            self.assertEqual(options.last_highlighted_id, "item_0_0")

            app.schema[0].insert(0, ConfigItem(
                label="Inserted", key="inserted", type_="bool", default=False, group="Items"
            ))
            app._rebuild_indexes()
            app._refresh_all_ui()
            await pilot.pause()
            self.assertEqual(options.scroll_y, 15)
            self.assertEqual(options.last_highlighted_id, "item_0_1")

    async def test_wheel_keyboard_resize_and_repeated_help_refresh(self):
        key = ("fixture", "")
        items = [ConfigItem(label=f"Device {i}", key=f"device{i}", type_="bool", default=False,
                            extended_help=f"HELP {i}") for i in range(50)]
        app = DuskyTUI(engine_pool={key: FakeEngine()}, default_engine_key=key,
                       schema={0: items}, tabs=["Devices"], enable_user_presets=False)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            options = app.query_one("#list-0", ConfigOptionList)
            initial_option = options.get_option("item_0_0")
            for _ in range(8):
                options.post_message(MouseScrollDown(options, 2, 2, 0, 1, 0, False, False, False))
            await pilot.pause(0.4)
            scroll = options.scroll_y
            self.assertGreater(scroll, 0)
            for _ in range(5):
                app._refresh_all_ui()
                await pilot.pause()
                self.assertEqual(options.scroll_y, scroll)
                self.assertIs(options.get_option("item_0_0"), initial_option)
            await pilot.press("?")
            await pilot.pause()
            self.assertIn("HELP 0", app.query_one("#help-markdown", Markdown)._dusky_help_text)
            await pilot.resize_terminal(60, 20)
            await pilot.press("pagedown", "down")
            await pilot.pause()
            selected = options.last_highlighted_id
            app._refresh_all_ui()
            await pilot.pause()
            self.assertEqual(options.last_highlighted_id, selected)
            self.assertIn("HELP", app.query_one("#help-markdown", Markdown)._dusky_help_text)

    async def test_hidden_tab_refresh_does_not_replace_visible_help(self):
        key = ("fixture", "")
        app = DuskyTUI(
            engine_pool={key: FakeEngine()}, default_engine_key=key,
            schema={
                0: [ConfigItem(label="Visible", key="visible", type_="bool", default=False, extended_help="VISIBLE HELP")],
                1: [ConfigItem(label="Hidden", key="hidden", type_="bool", default=False, extended_help="HIDDEN HELP")],
            },
            tabs=["First", "Second"], enable_user_presets=False,
        )
        async with app.run_test(size=(80, 18)) as pilot:
            await pilot.pause()
            app.action_toggle_help()
            shown = []
            original = app._update_help_panel

            def capture(item):
                shown.append(item.key)
                original(item)

            app._update_help_panel = capture
            app._populate_option_list(1)
            await pilot.pause()
            self.assertNotIn("hidden", shown)
            app.query_one(Tabs).active = "tab-id-1"
            await pilot.pause()
            self.assertEqual(app.query_one("#help-markdown", Markdown)._dusky_help_text, "HIDDEN HELP")

    async def test_removed_selected_child_returns_to_parent(self):
        key = ("fixture", "")
        parent = ConfigItem(label="Device", key="device", type_="menu", default=None, is_parent=True, expanded=True)
        child = ConfigItem(label="Address", key="address", type_="bool", default=False, parent_ref="device")
        other = ConfigItem(label="Unrelated", key="other", type_="bool", default=False)
        app = DuskyTUI(engine_pool={key: FakeEngine()}, default_engine_key=key,
                       schema={0: [parent, child, other]}, tabs=["Devices"], enable_user_presets=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            options = app.query_one("#list-0", ConfigOptionList)
            options.highlighted = options.get_option_index("item_0_1")
            await pilot.pause()
            app.schema[0] = [parent, other]
            app._rebuild_indexes()
            app._refresh_all_ui()
            await pilot.pause()
            self.assertEqual(options.last_highlighted_id, "item_0_0")

    async def test_inventory_replacement_waits_for_dialog_and_save(self):
        key = ("fixture", "")
        original = ConfigItem(label="Target", key="target", type_="bool", default=False)
        app = DuskyTUI(engine_pool={key: FakeEngine()}, default_engine_key=key,
                       schema={0: [original]}, tabs=["Networks"], enable_user_presets=False)
        fresh = [ConfigItem(label="Other target", key="other", type_="bool", default=False)]
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(ConfirmDialog("Confirm target?"))
            await pilot.pause()
            self.assertFalse(app._replace_dynamic_tabs({0: fresh}))
            self.assertIs(app.schema[0][0], original)
            app.screen.dismiss(False)
            await pilot.pause()
            task = asyncio.create_task(asyncio.Event().wait())
            app._save_tasks.add(task)
            self.assertFalse(app._replace_dynamic_tabs({0: fresh}))
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            app._save_tasks.discard(task)
            self.assertTrue(app._replace_dynamic_tabs({0: fresh}))
            self.assertEqual(app.schema[0][0].key, "other")

    async def test_dynamic_inventory_remaps_history_and_preserves_pending_edit(self):
        key = ("fixture", "")
        first = ConfigItem(label="First", key="first", type_="bool", default=False)
        second = ConfigItem(label="Second", key="second", type_="bool", default=False)
        app = DuskyTUI(
            engine_pool={key: FakeEngine()}, default_engine_key=key,
            schema={0: [first, second]}, tabs=["Networks"],
            enable_user_presets=False,
        )
        async with app.run_test(size=(80, 18)) as pilot:
            await pilot.pause()
            second.value = True
            app.pending_commits.add((0, 1))
            app.undo_stack.append([(0, 1, False, True)])
            fresh = [
                ConfigItem(label="Added", key="added", type_="bool", default=False),
                ConfigItem(label="First", key="first", type_="bool", default=False),
                ConfigItem(label="Second updated", key="second", type_="bool", default=False),
            ]
            self.assertTrue(app._replace_dynamic_tabs({0: fresh}))
            app._rebuild_indexes()
            app._refresh_all_ui()
            await pilot.pause()
            self.assertIs(app.schema[0][2], second)
            self.assertTrue(second.value)
            self.assertEqual(second.label, "Second updated")
            self.assertEqual(app.pending_commits, {(0, 2)})
            self.assertEqual(list(app.undo_stack), [[(0, 2, False, True)]])
            self.assertEqual(app._committed[(0, 0)], False)

    async def test_custom_dashboard_keeps_its_action_list(self):
        key = ("fixture", "")
        app = DuskyTUI(
            engine_pool={key: FakeEngine()}, default_engine_key=key,
            schema={0: [
                ConfigItem(label="Metric", key="metric", type_="bool", default=False, group="Info"),
                ConfigItem(label="Disconnect", key="disconnect", type_="bool", default=False, group="Actions"),
            ]},
            tabs=["Status"], enable_user_presets=False,
            custom_views={0: {"view": lambda: "Dashboard", "show_options": True, "option_groups": {"Actions"}}},
        )
        async with app.run_test(size=(80, 18)) as pilot:
            await pilot.pause()
            options = app.query_one("#list-0", ConfigOptionList)
            self.assertEqual(options.option_count, 2)
            self.assertEqual(options.get_option_at_index(1).id, "item_0_1")


if __name__ == "__main__":
    unittest.main()
