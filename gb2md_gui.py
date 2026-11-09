#!/usr/bin/env python3
"""Small PyQt5 front end for the GB2MD command-line compiler."""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

from PyQt5.QtCore import QProcess, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


ROOT = Path(__file__).resolve().parent
TEST_ROMS = (ROOT / "test_roms").resolve()


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def suggested_output(rom: Path) -> Path:
    """Return a stable generated-build path outside the fixture tree."""
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", rom.stem).strip("-.")
    return ROOT / "gui-builds" / (safe_name or "rom")


def validate_inputs(rom_text: str, output_text: str, steps: int) -> tuple[Path, Path]:
    rom = Path(rom_text).expanduser().resolve()
    output = Path(output_text).expanduser().resolve()

    if not rom.is_file():
        raise ValueError("Select an existing Game Boy ROM.")
    if rom.suffix.lower() not in {".gb", ".gbc"}:
        raise ValueError("The input file must have a .gb or .gbc extension.")
    if rom.stat().st_size < 0x150:
        raise ValueError("The selected file is too small to contain a Game Boy header.")
    if not output_text.strip():
        raise ValueError("Choose an output folder.")
    if _inside(output, TEST_ROMS):
        raise ValueError("Build output cannot be placed inside the immutable test_roms folder.")
    if steps <= 0:
        raise ValueError("Trace budget must be greater than zero.")
    return rom, output


def compiler_command(rom: Path, output: Path, steps: int, auto_steps: bool = False,
                     auto_max_steps: int = 50_000_000, auto_inputs: bool = False,
                     input_max_branches: int = 128, input_max_depth: int = 4,
                     input_max_steps: int = 20_000_000,
                     input_sweep_steps: int = 0) -> tuple[str, list[str]]:
    if input_sweep_steps<0 or (input_sweep_steps and not auto_inputs):
        raise ValueError('Long input sweeps require controller exploration.')
    arguments = [
        str(ROOT / "build_recompiled.py"),
        str(rom),
        "--out",
        str(output),
        "--steps",
        str(steps),
    ]
    if auto_steps:
        arguments += ["--auto-steps", "--auto-max-steps", str(auto_max_steps)]
    if auto_inputs:
        arguments += ["--auto-inputs", "--input-max-branches", str(input_max_branches),
                      "--input-max-depth", str(input_max_depth),
                      "--input-max-steps", str(input_max_steps)]
        if input_sweep_steps:
            arguments += ["--input-sweep-steps", str(input_sweep_steps)]
    return sys.executable, arguments


class ConverterWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.process: QProcess | None = None
        self.output_path: Path | None = None
        self.setWindowTitle("GB2MD — ROM Converter")
        self.resize(680, 650)

        self.rom_edit = QLineEdit()
        self.rom_edit.setPlaceholderText("Select a .gb or .gbc file")
        rom_button = QPushButton("Browse…")
        rom_button.clicked.connect(self.choose_rom)

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Choose destination")
        output_button = QPushButton("Browse…")
        output_button.clicked.connect(self.choose_output)

        self.steps = QSpinBox()
        self.steps.setRange(1, 2_000_000_000)
        self.steps.setValue(15_000_000)
        self.steps.setSingleStep(100_000)
        self.steps.setGroupSeparatorShown(True)
        self.steps.setSuffix(" steps")
        self.auto_steps = QCheckBox("Automatically extend while coverage grows")
        self.auto_max = QSpinBox()
        self.auto_max.setRange(1, 2_000_000_000)
        self.auto_max.setValue(50_000_000)
        self.auto_max.setGroupSeparatorShown(True)
        self.auto_max.setSuffix(" steps")
        self.auto_max.setEnabled(False)
        self.auto_steps.toggled.connect(self.auto_max.setEnabled)
        self.auto_inputs = QCheckBox("Explore controller inputs (experimental)")
        self.input_branches = QSpinBox()
        self.input_branches.setRange(1, 10000)
        self.input_branches.setValue(128)
        self.input_depth = QSpinBox()
        self.input_depth.setRange(1, 32)
        self.input_depth.setValue(4)
        self.input_max_steps = QSpinBox()
        self.input_max_steps.setRange(1, 2_000_000_000)
        self.input_max_steps.setValue(20_000_000)
        self.input_max_steps.setGroupSeparatorShown(True)
        self.input_max_steps.setSuffix(" steps")
        self.input_sweep_steps = QSpinBox()
        self.input_sweep_steps.setRange(0,2_000_000_000)
        self.input_sweep_steps.setGroupSeparatorShown(True)
        self.input_sweep_steps.setSuffix(" steps")
        self.input_sweep_steps.setSpecialValueText("Off")
        self.input_sweep_steps.setToolTip(
            "Optional varied Start/A presses before short input branches. "
            "Uses the input safety limit, not an additional budget. "
            "This heuristic does not guarantee complete coverage.")
        self.auto_inputs.setChecked(True)
        for control in (self.input_branches,self.input_depth,self.input_max_steps,self.input_sweep_steps):
            control.setEnabled(True)
            self.auto_inputs.toggled.connect(control.setEnabled)

        form = QFormLayout()
        form.setSpacing(14)
        form.addRow("Game Boy ROM", self._picker_row(self.rom_edit, rom_button))
        form.addRow("Output folder", self._picker_row(self.output_edit, output_button))
        form.addRow("Trace budget", self.steps)
        form.addRow("Auto steps", self.auto_steps)
        form.addRow("Safety limit", self.auto_max)
        form.addRow("Input exploration", self.auto_inputs)
        form.addRow("Branch limit", self.input_branches)
        form.addRow("Input depth", self.input_depth)
        form.addRow("Input safety limit", self.input_max_steps)
        form.addRow("Long input sweep", self.input_sweep_steps)

        self.compile_button = QPushButton("Compile ROM")
        self.compile_button.setObjectName("compileButton")
        self.compile_button.clicked.connect(self.start_compile)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_compile)
        self.open_button = QPushButton("Open output folder")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_output)

        actions = QHBoxLayout()
        actions.addWidget(self.compile_button, 1)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.open_button)

        self.status = QLabel("Ready")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Build output and errors are displayed here.")

        layout = QVBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        title = QLabel("GB2MD — ROM Converter")
        title.setObjectName("title")
        layout.addWidget(title)
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(self.status)
        layout.addWidget(self.log, 1)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #111; color: #ddd; }
            QLineEdit, QSpinBox, QPlainTextEdit {
                background: #1b1b1b; border: 1px solid #444; border-radius: 5px;
                padding: 7px; color: #eee;
            }
            QPushButton { background: #292929; border: 1px solid #555; border-radius: 6px; padding: 7px 12px; }
            QPushButton:hover { background: #363636; }
            QPushButton:disabled { color: #777; border-color: #333; }
            QPushButton#compileButton { background: #e8e8e8; color: #111; font-weight: 600; }
            QLabel#title { font-size: 18px; font-weight: 700; padding-bottom: 8px; }
            """
        )

    @staticmethod
    def _picker_row(edit: QLineEdit, button: QPushButton) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit, 1)
        layout.addWidget(button)
        return row

    def choose_rom(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Game Boy ROM",
            str(ROOT),
            "Game Boy ROMs (*.gb *.gbc);;All files (*)",
        )
        if filename:
            rom = Path(filename).resolve()
            previous_rom = self.rom_edit.text().strip()
            current_output = self.output_edit.text().strip()
            follows_default = not current_output or (
                bool(previous_rom) and Path(current_output).expanduser().resolve()
                == suggested_output(Path(previous_rom)).resolve()
            )
            self.rom_edit.setText(str(rom))
            if follows_default:
                self.output_edit.setText(str(suggested_output(rom)))

    def choose_output(self) -> None:
        start = self.output_edit.text().strip() or str(ROOT / "gui-builds")
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", start)
        if folder:
            self.output_edit.setText(str(Path(folder).resolve()))

    def start_compile(self) -> None:
        if self.process is not None:
            return
        try:
            rom, output = validate_inputs(
                self.rom_edit.text(), self.output_edit.text(), self.steps.value()
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Cannot compile", str(exc))
            return

        binary = output / "recompiled.md"
        if binary.exists():
            answer = QMessageBox.question(
                self,
                "Replace generated build?",
                f"This output folder already contains a build:\n{output}\n\nContinue and update it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        output.mkdir(parents=True, exist_ok=True)
        program, arguments = compiler_command(rom, output, self.steps.value(), self.auto_steps.isChecked(), self.auto_max.value(), self.auto_inputs.isChecked(), self.input_branches.value(), self.input_depth.value(), self.input_max_steps.value(),self.input_sweep_steps.value() if self.auto_inputs.isChecked() else 0)
        self.output_path = output
        self.log.clear()
        self.log.appendPlainText("$ " + shlex.join([program, *arguments]))
        self.status.setText("Compiling… Large trace budgets may take several minutes.")
        self.compile_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.open_button.setEnabled(False)

        process = QProcess(self)
        self.process = process
        process.setWorkingDirectory(str(ROOT))
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(self.read_process_output)
        process.errorOccurred.connect(self.process_error)
        process.finished.connect(self.process_finished)
        process.start(program, arguments)

    def read_process_output(self) -> None:
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if text:
            self.log.moveCursor(self.log.textCursor().End)
            self.log.insertPlainText(text)
            self.log.ensureCursorVisible()

    def process_error(self, _error: QProcess.ProcessError) -> None:
        if self.process is not None:
            self.log.appendPlainText("\nProcess error: " + self.process.errorString())

    def process_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        self.read_process_output()
        output = self.output_path
        success = exit_code == 0 and output is not None and (output / "recompiled.md").is_file()
        if success:
            binary = output / "recompiled.md"
            self.status.setText(f"Build complete: {binary}")
            self.log.appendPlainText(f"\nBuild complete: {binary}")
            self.open_button.setEnabled(True)
        else:
            self.status.setText(f"Build failed (exit code {exit_code}). See the log below.")
            self.log.appendPlainText(f"\nBuild failed with exit code {exit_code}.")
        self.process = None
        self.compile_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def cancel_compile(self) -> None:
        if self.process is None:
            return
        self.status.setText("Stopping compiler…")
        self.process.terminate()
        process = self.process
        QTimer.singleShot(3000, lambda: process.kill() if process.state() != QProcess.NotRunning else None)

    def open_output(self) -> None:
        if self.output_path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output_path)))

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.process is None:
            event.accept()
            return
        answer = QMessageBox.question(
            self,
            "Compiler is running",
            "Stop the compiler and close the window?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.process.kill()
            event.accept()
        else:
            event.ignore()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("GB2MD")
    window = ConverterWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
