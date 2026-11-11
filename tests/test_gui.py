from pathlib import Path
import os
import tempfile
import unittest

from gb2md_gui import ROOT, compiler_command, suggested_output, validate_inputs


def make_rom(path: Path) -> Path:
    path.write_bytes(bytes(0x150))
    return path


class GuiHelpersTest(unittest.TestCase):
    def test_rom_change_updates_default_but_preserves_custom_output(self):
        from unittest.mock import patch
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication
        from gb2md_gui import ConverterWindow
        app=QApplication.instance() or QApplication([])
        window=ConverterWindow()
        try:
            window.rom_edit.setText('/tmp/first.gb')
            window.output_edit.setText(str(suggested_output(Path('/tmp/first.gb'))))
            with patch('gb2md_gui.QFileDialog.getOpenFileName',return_value=('/tmp/second.gb','')):
                window.choose_rom()
            self.assertEqual(window.output_edit.text(),str(suggested_output(Path('/tmp/second.gb'))))
            window.output_edit.setText('/tmp/custom-build')
            with patch('gb2md_gui.QFileDialog.getOpenFileName',return_value=('/tmp/third.gb','')):
                window.choose_rom()
            self.assertEqual(window.output_edit.text(),'/tmp/custom-build')
        finally:
            window.close()

    def test_auto_input_exploration_defaults_to_verified_settings(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication
        from gb2md_gui import ConverterWindow
        app=QApplication.instance() or QApplication([])
        window=ConverterWindow()
        try:
            self.assertTrue(window.auto_inputs.isChecked())
            self.assertFalse(window.show_fps.isChecked())
            self.assertEqual(window.input_branches.value(),128)
            self.assertEqual(window.input_depth.value(),4)
            self.assertEqual(window.input_max_steps.value(),20_000_000)
            self.assertEqual(window.input_sweep_steps.value(),0)
            window.auto_inputs.setChecked(False)
            self.assertFalse(window.input_sweep_steps.isEnabled())
        finally:
            window.close()

    def test_suggested_output_is_outside_fixture_tree(self):
        output = suggested_output(Path("/tmp") / "A Test Game.gb")
        self.assertEqual(output, ROOT / "gui-builds" / "A-Test-Game")

    def test_validate_inputs_and_construct_command(self):
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            rom = make_rom(temp / "test.gb")
            output = temp / "build"
            resolved_rom, resolved_output = validate_inputs(str(rom), str(output), 1234)
            program, arguments = compiler_command(resolved_rom, resolved_output, 1234)
            self.assertTrue(Path(program).name.startswith("python"))
            self.assertEqual(
                arguments,
                [
                    str(ROOT / "build_recompiled.py"),
                    str(rom.resolve()),
                    "--out",
                    str(output.resolve()),
                    "--steps",
                    "1234",
                ],
            )
            _, auto_arguments = compiler_command(resolved_rom, resolved_output, 1234, True, 9999)
            self.assertEqual(auto_arguments[-3:], ["--auto-steps", "--auto-max-steps", "9999"])
            _, input_arguments = compiler_command(resolved_rom, resolved_output, 1234, auto_inputs=True, input_max_branches=17, input_max_depth=3, input_max_steps=999)
            self.assertEqual(input_arguments[-7:], ["--auto-inputs", "--input-max-branches", "17", "--input-max-depth", "3", "--input-max-steps", "999"])
            _, sweep_arguments=compiler_command(resolved_rom,resolved_output,1234,
                auto_inputs=True,input_max_steps=1000,input_sweep_steps=700)
            self.assertEqual(sweep_arguments[-2:],["--input-sweep-steps","700"])
            with self.assertRaises(ValueError):
                compiler_command(resolved_rom,resolved_output,1234,input_sweep_steps=700)

    def test_rejects_wrong_extension(self):
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            for name in ("not-a-rom.bin", "not-a-rom.txt"):
                rom = make_rom(temp / name)
                with self.assertRaisesRegex(ValueError, r"\.gb or \.gbc"):
                    validate_inputs(str(rom), str(temp / "build"), 1)

    def test_rejects_missing_rom(self):
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            with self.assertRaisesRegex(ValueError, "existing"):
                validate_inputs(str(temp / "missing.gb"), str(temp / "build"), 1)

    def test_rejects_output_inside_test_roms(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = make_rom(Path(folder) / "fixture.gb")
            with self.assertRaisesRegex(ValueError, "test_roms"):
                validate_inputs(str(fixture), str(ROOT / "test_roms" / "generated"), 1)


if __name__ == "__main__":
    unittest.main()
