# sammie/export_dialog.py
"""
Export dialog for video and sequence exports.
Refactored for clarity and extensibility.
"""
import os
import datetime
from dataclasses import replace
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QGridLayout,
    QPushButton, QLabel, QLineEdit, QComboBox, QSpinBox, QCheckBox,
    QFileDialog, QProgressDialog, QMessageBox, QWidget
)
from PySide6.QtCore import Qt
from sammie.core import VideoInfo, input_base_name, source_frame_number, source_frame_name
from sammie.gui_widgets import show_message_dialog
from sammie.export_formats import FormatRegistry, ExportSettings
from sammie.export_workers import VideoExportWorker, SequenceExportWorker


# The outputs offered as checkboxes, laid out as the grid shows them. Ticked
# outputs are exported one after another in this order.
OUTPUT_GRID = [
    ("Segmentation", ['Segmentation-Matte', 'Segmentation-Alpha', 'Segmentation-BGcolor']),
    ("Matting", ['Matting-Matte', 'Matting-Alpha', 'Matting-BGcolor']),
]
OUTPUT_TYPES = [t for _, row in OUTPUT_GRID for t in row] + ['ObjectRemoval']
MATTING_TYPES = ('Matting-Matte', 'Matting-Alpha', 'Matting-BGcolor')


class ExportPathManager:
    """Manages path generation and template resolution"""
    
    def __init__(self, settings_mgr):
        self.settings_mgr = settings_mgr
    
    def resolve_template(self, template: str, format_id: str, output_type: str, 
                        object_id: int = None) -> str:
        """Resolve template tags to actual values"""
        # Get input file info
        input_file = self.settings_mgr.get_session_setting("video_file_path", "")
        base_name = input_base_name(input_file) if input_file else "video"
        
        # Get in/out points
        total_frames = VideoInfo.total_frames
        # Unset markers are stored as None, which the defaults here don't catch
        in_point = self.settings_mgr.get_session_setting("in_point", None)
        out_point = self.settings_mgr.get_session_setting("out_point", None)
        if in_point is None:
            in_point = 0
        if out_point is None:
            out_point = total_frames - 1
        
        # Get timestamp
        now = datetime.datetime.now()
        
        # Handle object name/ID
        if object_id is not None and object_id != -1:
            object_names = self.settings_mgr.get_session_setting("object_names", {})
            raw_object_name = object_names.get(str(object_id), "")
            if not raw_object_name.strip():
                raw_object_name = f"object_{object_id}"
            sanitized_object_name = self._sanitize_name(raw_object_name)
            obj_id_str = str(object_id)
        else:
            sanitized_object_name = "all"
            obj_id_str = "all"
        
        # Tag replacement dictionary
        tag_values = {
            "input_name": base_name,
            "output_type": output_type,
            "codec": format_id,
            "object_id": obj_id_str,
            "object_name": sanitized_object_name,
            "in_point": str(source_frame_number(in_point)),
            "out_point": str(source_frame_number(out_point)),
            "date": now.strftime("%Y%m%d"),
            "time": now.strftime("%H%M%S"),
            "datetime": now.strftime("%Y%m%d_%H%M%S"),
        }
        
        result = template
        for tag, value in tag_values.items():
            result = result.replace(f"{{{tag}}}", str(value))
        
        return result
    
    def generate_output_path(self, output_dir: str, template: str, format_id: str,
                           output_type: str, object_id: int = None) -> str:
        """Generate full output path with extension"""
        resolved_name = self.resolve_template(template, format_id, output_type, object_id)
        format_obj = FormatRegistry.get_format(format_id)
        ext = format_obj.file_extension
        
        # For sequences, don't add extension here (will be added per frame)
        if format_obj.is_sequence:
            return os.path.join(output_dir, resolved_name)
        else:
            return os.path.join(output_dir, resolved_name + ext)
    
    def check_existing_files(self, paths: list) -> list:
        """Check which files already exist"""
        return [p for p in paths if os.path.exists(p)]
    
    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Sanitize name for use in filenames"""
        import re
        if not name:
            return "unnamed"
        sanitized = re.sub(r'[^\w]', '_', name)
        sanitized = re.sub(r'_+', '_', sanitized)
        sanitized = sanitized.strip('_')
        return sanitized[:20] if len(sanitized) > 20 else sanitized or "unnamed"


class ExportDialog(QDialog):
    """Main export dialog"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.export_worker = None
        self.progress_dialog = None
        self.path_manager = ExportPathManager(parent.settings_mgr) if parent else None
        self.current_format = None
        
        self.setWindowTitle("Export Video")
        self.setModal(True)
        self.resize(500, 520)
        
        self._init_ui()
        self._load_saved_settings()
    
    def _init_ui(self):
        """Initialize dialog UI"""
        layout = QVBoxLayout(self)
        
        self._create_output_section(layout)
        self._create_settings_section(layout)
        self._create_buttons(layout)
        
        # Set initial format
        if self.format_combo.count() > 0:
            self._on_format_changed(0)
    
    def _create_output_section(self, layout):
        """Create output file selection section"""
        output_group = QGroupBox("Output")
        output_layout = QFormLayout(output_group)
        
        # Output folder
        folder_layout = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Select output folder...")
        self.folder_edit.textChanged.connect(self._update_filename_preview)
        folder_layout.addWidget(self.folder_edit)
        
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._browse_output_folder)
        folder_layout.addWidget(self.browse_btn)
        
        output_layout.addRow("Output Folder:", folder_layout)
        
        # Use input folder checkbox
        self.use_input_folder_checkbox = QCheckBox("Use same folder as input file")
        self.use_input_folder_checkbox.stateChanged.connect(self._on_use_input_folder_changed)
        output_layout.addRow("", self.use_input_folder_checkbox)
        
        # Filename template
        template_layout = QHBoxLayout()
        self.filename_template_edit = QLineEdit()
        self.filename_template_edit.setPlaceholderText("{input_name}-{output_type}")
        self.filename_template_edit.textChanged.connect(self._update_filename_preview)
        template_layout.addWidget(self.filename_template_edit)
        
        self.tag_dropdown = QComboBox()
        self.tag_dropdown.addItem("Insert tag...")
        self.tag_dropdown.addItems([
            "{input_name}", "{output_type}", "{object_id}", "{object_name}",
            "{codec}", "{in_point}", "{out_point}", "{date}", "{time}", "{datetime}"
        ])
        self.tag_dropdown.currentIndexChanged.connect(self._insert_tag)
        template_layout.addWidget(self.tag_dropdown)
        
        output_layout.addRow("Filename:", template_layout)
        
        # Preview
        self.filename_preview_label = QLabel()
        self.filename_preview_label.setStyleSheet("color: gray; font-style: italic;")
        self.filename_preview_label.setWordWrap(True)
        output_layout.addRow("Preview:", self.filename_preview_label)
        
        layout.addWidget(output_group)
    
    def _create_settings_section(self, layout):
        """Create export settings section"""
        settings_group = QGroupBox("Format & Settings")
        settings_layout = QFormLayout(settings_group)
        
        # Format selection
        self.format_combo = QComboBox()
        for fmt in FormatRegistry.get_all_formats():
            self.format_combo.addItem(fmt.display_name, fmt.format_id)
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        settings_layout.addRow("Export Format:", self.format_combo)
        
        # Outputs - any number can be ticked and are exported in one go, all
        # with the same format and settings
        outputs_widget = QWidget()
        outputs_grid = QGridLayout(outputs_widget)
        outputs_grid.setContentsMargins(0, 0, 0, 0)
        for col, heading in enumerate(["Matte", "Alpha", "BG colour"], start=1):
            outputs_grid.addWidget(QLabel(heading), 0, col, Qt.AlignCenter)
        self.output_checkboxes = {}
        for row, (label, types) in enumerate(OUTPUT_GRID, start=1):
            outputs_grid.addWidget(QLabel(label), row, 0)
            for col, output_type in enumerate(types, start=1):
                self._add_output_checkbox(outputs_grid, output_type, row, col)
        outputs_grid.addWidget(QLabel("Object removal"), len(OUTPUT_GRID) + 1, 0)
        self._add_output_checkbox(outputs_grid, 'ObjectRemoval', len(OUTPUT_GRID) + 1, 1)
        settings_layout.addRow("Outputs:", outputs_widget)
        
        # Object selection
        self.object_id_combo = QComboBox()
        self.object_id_combo.addItem("All Objects", -1)
        self.object_id_combo.currentIndexChanged.connect(self._update_filename_preview)
        settings_layout.addRow("Export Object:", self.object_id_combo)
        
        # Export multiple objects checkbox
        self.export_multiple_checkbox = QCheckBox("Export separate file for each object")
        self.export_multiple_checkbox.stateChanged.connect(self._on_export_multiple_changed)
        settings_layout.addRow("", self.export_multiple_checkbox)
        
        # Quality setting
        self.quantizer_spin = QSpinBox()
        self.quantizer_spin.setRange(0, 51)
        self.quantizer_spin.setValue(14)
        self.quantizer_spin.setToolTip("Lower values = higher quality, larger file size")
        settings_layout.addRow("Quality (CRF):", self.quantizer_spin)
        self.quantizer_label = settings_layout.labelForField(self.quantizer_spin)
        
        # Antialiasing
        self.antialias_checkbox = QCheckBox("Antialiasing")
        self.antialias_checkbox.setChecked(False)
        settings_layout.addRow("", self.antialias_checkbox)
        
        # Include original (EXR only)
        self.include_original_checkbox = QCheckBox("Include original frame as layer")
        self.include_original_checkbox.setVisible(False)
        settings_layout.addRow("", self.include_original_checkbox)
        
        # In/Out points
        self.use_inout_checkbox = QCheckBox("Export only between in/out markers")
        self.use_inout_checkbox.setChecked(True)
        settings_layout.addRow("", self.use_inout_checkbox)
        
        layout.addWidget(settings_group)
    
    def _create_buttons(self, layout):
        """Create dialog buttons"""
        button_layout = QHBoxLayout()
        
        self.save_settings_btn = QPushButton("Save Settings")
        self.save_settings_btn.clicked.connect(self._save_current_settings)
        button_layout.addWidget(self.save_settings_btn)
        
        button_layout.addStretch()
        
        self.export_btn = QPushButton("Export")
        self.export_btn.clicked.connect(self._start_export)
        
        self.cancel_btn = QPushButton("Close")
        self.cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(self.export_btn)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
    
    # === UI Event Handlers ===
    
    def _browse_output_folder(self):
        """Browse for output folder"""
        folder = QFileDialog.getExistingDirectory(self, "Select Export Folder")
        if folder:
            self.folder_edit.setText(folder)
    
    def _on_use_input_folder_changed(self, state):
        """Handle use input folder checkbox change"""
        use_input = self.use_input_folder_checkbox.isChecked()
        self.folder_edit.setEnabled(not use_input)
        self.browse_btn.setEnabled(not use_input)
        self._update_filename_preview()
    
    def _insert_tag(self, index):
        """Insert template tag at cursor position"""
        if index <= 0:
            return
        
        tag = self.tag_dropdown.itemText(index)
        cursor_pos = self.filename_template_edit.cursorPosition()
        text = self.filename_template_edit.text()
        new_text = text[:cursor_pos] + tag + text[cursor_pos:]
        self.filename_template_edit.setText(new_text)
        self.filename_template_edit.setCursorPosition(cursor_pos + len(tag))
        self.tag_dropdown.setCurrentIndex(0)
    
    def _add_output_checkbox(self, grid, output_type, row, col):
        """Add one output's checkbox to the outputs grid"""
        checkbox = QCheckBox()
        checkbox.setToolTip(output_type)
        checkbox.stateChanged.connect(self._on_output_types_changed)
        grid.addWidget(checkbox, row, col, Qt.AlignCenter)
        self.output_checkboxes[output_type] = checkbox

    def _selected_output_types(self) -> list:
        """The ticked outputs the current format can produce, in export order"""
        return [t for t in OUTPUT_TYPES
                if self.output_checkboxes[t].isEnabled() and self.output_checkboxes[t].isChecked()]

    def _on_format_changed(self, index):
        """Handle format selection change"""
        format_id = self.format_combo.itemData(index)
        self.current_format = FormatRegistry.get_format(format_id)
        
        if not self.current_format:
            return
        
        # Outputs this format can't produce are greyed out and unticked
        available = self.current_format.get_available_output_types()
        for output_type, checkbox in self.output_checkboxes.items():
            checkbox.blockSignals(True)
            checkbox.setEnabled(output_type in available)
            if output_type not in available:
                checkbox.setChecked(False)
            checkbox.blockSignals(False)
        
        # Update UI visibility based on format capabilities
        self._update_ui_for_format()
        self._on_output_types_changed()
    
    def _on_output_types_changed(self):
        """Handle an output being ticked or unticked"""
        # Repopulate the object combo to reflect the correct source for these outputs
        self._repopulate_object_combo()
        self._update_object_controls()
        self._update_filename_preview()
    
    def _repopulate_object_combo(self):
        """Repopulate the object selection combo, keeping the current choice if it is still offered"""
        current = self.object_id_combo.currentData()
        self.object_id_combo.blockSignals(True)
        self.object_id_combo.clear()
        self.object_id_combo.addItem("All Objects", -1)
        for obj_id in self._get_available_object_ids(self._selected_output_types()):
            self.object_id_combo.addItem(f"Object {obj_id}", obj_id)
        index = self.object_id_combo.findData(current)
        self.object_id_combo.setCurrentIndex(max(index, 0))
        self.object_id_combo.blockSignals(False)

    def _update_ui_for_format(self):
        """Update UI controls based on current format"""
        if not self.current_format:
            return
        
        # Quality setting
        show_quality = self.current_format.supports_quality_setting
        self.quantizer_spin.setVisible(show_quality)
        self.quantizer_label.setVisible(show_quality)
        
        if show_quality:
            min_q, max_q = self.current_format.get_quality_range()
            self.quantizer_spin.setRange(min_q, max_q)
            self.quantizer_spin.setValue(self.current_format.get_default_quality())
            self.quantizer_label.setText(self.current_format.get_quality_label())
        
        # Include original
        show_include_original = self.current_format.supports_include_original
        self.include_original_checkbox.setVisible(show_include_original)
    
    def _update_object_controls(self):
        """Update object selection, per-object export and antialiasing for the ticked outputs"""
        if not self.current_format:
            return
        output_types = self._selected_output_types()
        # ObjectRemoval always uses all objects, so the object controls only
        # matter when something else is ticked alongside it
        only_removal = output_types == ['ObjectRemoval']
        
        show_multiple = self.current_format.supports_multiple_export and not only_removal
        self.export_multiple_checkbox.setVisible(show_multiple)
        if not show_multiple:
            self.export_multiple_checkbox.setChecked(False)
        
        if only_removal or self.current_format.format_id == 'exr':
            # EXR sequences always export all objects as layers
            self.object_id_combo.setCurrentIndex(0)
            self.object_id_combo.setEnabled(False)
        else:
            self.object_id_combo.setEnabled(not self.export_multiple_checkbox.isChecked())
        
        # Antialiasing (only for segmentation modes)
        self.antialias_checkbox.setVisible(
            any(t.startswith('Segmentation-') for t in output_types))
    
    def _on_export_multiple_changed(self, state):
        """Handle export multiple checkbox change"""
        export_multiple = self.export_multiple_checkbox.isChecked()
        self.object_id_combo.setEnabled(not export_multiple)
        self._update_filename_preview()
    
    def _update_filename_preview(self):
        """Update filename preview label"""
        if not self.current_format or not self.path_manager:
            return
        
        jobs = self._build_export_jobs()
        if not jobs:
            self.filename_preview_label.setText("Tick at least one output")
            return
        
        names = []
        for settings in jobs:
            output_paths, _ = self._generate_output_paths(settings)
            if self.current_format.is_sequence:
                names.append(f"{output_paths[0]}{self.current_format.file_extension}")
            else:
                names.extend(output_paths)
        
        if not names:
            self.filename_preview_label.setText("No objects found")
        elif len(names) == 1:
            self.filename_preview_label.setText(names[0])
        else:
            preview_text = "\n".join(os.path.basename(n) for n in names[:6])
            if len(names) > 6:
                preview_text += f"\n... and {len(names) - 6} more"
            self.filename_preview_label.setText(preview_text)
    
    # === Export Logic ===

    def _start_export(self):
        """Start exporting every ticked output, one after another"""
        if not self._validate_settings():
            return

        self._export_jobs = self._build_export_jobs()
        self._export_index = -1
        self._export_messages = []
        self._export_cancelled = False

        # Create progress dialog, shared by every output in the run
        self.progress_dialog = QProgressDialog("Exporting...", "Cancel", 0, 100, self)
        self.progress_dialog.setWindowTitle("Exporting")
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.setAutoReset(False)
        self.progress_dialog.canceled.connect(self._cancel_export)
        self.progress_dialog.show()

        # Disable export button
        self.export_btn.setEnabled(False)

        self._start_next_export()

    def _start_next_export(self):
        """Start the worker for the next output in the run"""
        self._export_index += 1
        settings = self._export_jobs[self._export_index]

        # Get points
        points = self.parent_window.point_manager.get_all_points()
        total_frames = VideoInfo.total_frames

        # Generate output paths
        output_paths, object_ids = self._generate_output_paths(settings)

        # Create appropriate worker
        if self.current_format.is_sequence:
            base_filename = os.path.basename(output_paths[0])
            self.export_worker = SequenceExportWorker(
                settings, points, total_frames, base_filename, self.parent_window
            )
        else:
            self.export_worker = VideoExportWorker(
                settings, points, total_frames, output_paths, object_ids, self.parent_window
            )

        # Connect signals
        self.export_worker.progress_updated.connect(self._update_progress)
        self.export_worker.status_updated.connect(self._update_status)
        self.export_worker.finished.connect(self._export_finished)

        self._update_status(self._get_initial_progress_text(settings, output_paths))
        self._update_progress(0)

        # Start export
        self.export_worker.start()

    def _build_export_jobs(self) -> list:
        """Build one set of export settings per ticked output, all sharing the rest of the UI"""
        # Get in/out points
        use_inout = self.use_inout_checkbox.isChecked()
        in_point = None
        out_point = None

        if use_inout and self.parent_window:
            settings_mgr = self.parent_window.settings_mgr
            in_point = settings_mgr.get_session_setting("in_point", None)
            out_point = settings_mgr.get_session_setting("out_point", None)

        # Get output directory
        if self.use_input_folder_checkbox.isChecked():
            input_file = self.parent_window.settings_mgr.get_session_setting("video_file_path", "")
            output_dir = os.path.dirname(input_file) if input_file else os.getcwd()
        else:
            output_dir = self.folder_edit.text() or os.getcwd()

        base = ExportSettings(
            format_id=self.current_format.format_id,
            output_dir=output_dir,
            filename_template=self.filename_template_edit.text().strip() or "{input_name}-{output_type}",
            output_type="",
            object_id=self.object_id_combo.currentData(),
            antialias=self.antialias_checkbox.isChecked(),
            quality=self.quantizer_spin.value(),
            use_inout=use_inout,
            in_point=in_point,
            out_point=out_point,
            include_original=self.include_original_checkbox.isChecked(),
            export_multiple=self.export_multiple_checkbox.isChecked()
        )

        jobs = []
        for output_type in self._selected_output_types():
            if output_type == 'ObjectRemoval':
                # ObjectRemoval always uses all objects, in one file
                jobs.append(replace(base, output_type=output_type, object_id=-1, export_multiple=False))
            else:
                jobs.append(replace(base, output_type=output_type))
        return jobs

    def _generate_output_paths(self, settings: ExportSettings) -> tuple:
        """Generate output paths and corresponding object IDs"""
        output_paths = []
        object_ids = []

        if settings.export_multiple:
            # Multiple files for different objects
            all_object_ids = self._get_available_object_ids([settings.output_type])
            for obj_id in all_object_ids:
                path = self.path_manager.generate_output_path(
                    settings.output_dir, settings.filename_template,
                    settings.format_id, settings.output_type, obj_id
                )
                output_paths.append(path)
                object_ids.append(obj_id)
        else:
            # Single file
            path = self.path_manager.generate_output_path(
                settings.output_dir, settings.filename_template,
                settings.format_id, settings.output_type, settings.object_id
            )
            output_paths.append(path)
            object_ids.append(settings.object_id)

        return output_paths, object_ids

    def _validate_settings(self) -> bool:
        """Validate export settings"""
        jobs = self._build_export_jobs()
        if not jobs:
            show_message_dialog(
                self, title="Invalid Settings",
                message="Tick at least one output to export.",
                type='warning'
            )
            return False

        template = self.filename_template_edit.text().strip() or "{input_name}-{output_type}"

        # Each output needs its own filename, or they would overwrite each other
        if len(jobs) > 1 and "{output_type}" not in template:
            show_message_dialog(
                self, title="Invalid Settings",
                message="When exporting more than one output, filename must include the {output_type} tag.",
                type='warning'
            )
            return False

        # Validate template for multiple export
        if any(job.export_multiple for job in jobs):
            if "{object_id}" not in template and "{object_name}" not in template:
                show_message_dialog(
                    self, title="Invalid Settings",
                    message="When exporting separate files for each object, filename must include either {object_id} or {object_name} tag.",
                    type='warning'
                )
                return False

        # Validate output directory
        if not self._validate_output_directory():
            return False

        # Check for existing files across every output
        existing = []
        for settings in jobs:
            output_paths, _ = self._generate_output_paths(settings)
            if self.current_format.is_sequence:
                # For sequences, check if any frame files exist
                existing.extend(self._check_sequence_files_exist(output_paths[0], settings))
            else:
                # For video, check file existence
                existing.extend(os.path.basename(p)
                                for p in self.path_manager.check_existing_files(output_paths))
        if existing:
            return self._confirm_overwrite(existing)

        return True

    def _validate_output_directory(self) -> bool:
        """Validate and create output directory if needed"""
        if self.use_input_folder_checkbox.isChecked():
            input_file = self.parent_window.settings_mgr.get_session_setting("video_file_path", "")
            folder = os.path.dirname(input_file) if input_file else ""
            if not folder or not os.path.exists(folder):
                show_message_dialog(
                    self, title="Invalid Settings",
                    message="Input file directory is not available. Please select an output folder manually.",
                    type="warning"
                )
                return False
        else:
            folder = self.folder_edit.text().strip()
            if not folder:
                show_message_dialog(
                    self, title="Invalid Settings",
                    message="Please select an output folder.",
                    type="warning"
                )
                return False
            
            if not os.path.exists(folder):
                reply = QMessageBox.question(
                    self, "Create Folder?",
                    f"The output folder does not exist:\n\n{folder}\n\nDo you want to create it?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                if reply != QMessageBox.Yes:
                    return False
                
                try:
                    os.makedirs(folder, exist_ok=True)
                except OSError as e:
                    show_message_dialog(
                        self, title="Error",
                        message=f"Could not create output directory:\n{e}",
                        type="critical"
                    )
                    return False
        
        return True
    
    def _check_sequence_files_exist(self, base_path: str, settings: ExportSettings) -> list:
        """Check if sequence files exist"""
        existing_files = []
        total_frames = VideoInfo.total_frames
        
        # Determine frame range
        if settings.use_inout and settings.in_point is not None and settings.out_point is not None:
            start_frame = max(0, settings.in_point)
            end_frame = min(total_frames - 1, settings.out_point)
        else:
            start_frame = 0
            end_frame = total_frames - 1
        
        # Check first few frames
        for frame_num in range(start_frame, min(start_frame + 5, end_frame + 1)):
            if self.current_format.format_id == 'exr':
                frame_file = f"{base_path}.{source_frame_name(frame_num)}.exr"
            else:  # PNG
                frame_file = f"{base_path}.{source_frame_name(frame_num)}.png"
            
            if os.path.exists(frame_file):
                existing_files.append(os.path.basename(frame_file))
        
        return existing_files
    
    def _confirm_overwrite(self, existing_files: list) -> bool:
        """Confirm overwriting existing files, from any of the outputs"""
        files_text = "\n".join(existing_files[:8])
        if len(existing_files) > 8:
            files_text += f"\n... and {len(existing_files) - 8} more"

        reply = QMessageBox.question(
            self, "Files Exist",
            f"These files already exist:\n\n{files_text}\n\nDo you want to overwrite them?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        return reply == QMessageBox.Yes

    def _get_initial_progress_text(self, settings: ExportSettings, output_paths: list) -> str:
        """Get initial progress dialog text"""
        if self.current_format.is_sequence:
            total_frames = VideoInfo.total_frames
            if settings.use_inout and settings.in_point is not None and settings.out_point is not None:
                frame_count = settings.out_point - settings.in_point + 1
            else:
                frame_count = total_frames
            return f"Exporting {frame_count} {self.current_format.display_name} frames..."
        elif len(output_paths) > 1:
            return f"Exporting {len(output_paths)} videos..."
        else:
            return "Exporting video..."

    # === Progress Handling ===

    def _update_progress(self, value):
        """Update progress dialog, as a share of the whole run"""
        if self.progress_dialog:
            count = len(self._export_jobs)
            self.progress_dialog.setValue((self._export_index * 100 + value) // count)

    def _update_status(self, message):
        """Update status message, saying which output it belongs to"""
        if self.progress_dialog:
            count = len(self._export_jobs)
            if count > 1:
                output_type = self._export_jobs[self._export_index].output_type
                message = f"Output {self._export_index + 1} of {count}: {output_type}\n{message}"
            self.progress_dialog.setLabelText(message)

    def _cancel_export(self):
        """Cancel the export process, including any outputs not started yet"""
        self._export_cancelled = True
        if self.export_worker:
            self.export_worker.cancel()

    def _export_finished(self, success, message):
        """Handle one output finishing; start the next or report the run"""
        # Clean up worker
        if self.export_worker:
            self.export_worker.quit()
            self.export_worker.wait()
            self.export_worker = None

        count = len(self._export_jobs)
        if count > 1:
            message = f"{self._export_jobs[self._export_index].output_type}: {message}"
        self._export_messages.append(message)

        more_to_do = self._export_index + 1 < count
        if success and more_to_do and not self._export_cancelled:
            self._start_next_export()
            return

        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        self.export_btn.setEnabled(True)

        # Show completion message
        if success and not more_to_do:
            show_message_dialog(self, title="Export Complete",
                                message="\n\n".join(self._export_messages), type="info")
        else:
            skipped = count - self._export_index - 1
            if skipped:
                self._export_messages.append(
                    f"{skipped} remaining output{'s' if skipped != 1 else ''} not exported.")
            show_message_dialog(self, title="Export Failed",
                                message="\n\n".join(self._export_messages), type="critical")

    # === Settings Persistence ===
    
    def _save_current_settings(self):
        """Save current dialog settings to application settings"""
        if not self.parent_window or not hasattr(self.parent_window, 'settings_mgr'):
            return
        
        settings_mgr = self.parent_window.settings_mgr
        
        # Save current UI values
        settings_mgr.set_app_setting('export_codec', self.current_format.format_id)
        settings_mgr.set_app_setting('export_output_types', self._selected_output_types())
        settings_mgr.set_app_setting('export_use_input_folder', self.use_input_folder_checkbox.isChecked())
        settings_mgr.set_app_setting('export_filename_template', self.filename_template_edit.text())
        settings_mgr.set_app_setting('export_antialias', self.antialias_checkbox.isChecked())
        settings_mgr.set_app_setting('export_quantizer', self.quantizer_spin.value())
        settings_mgr.set_app_setting('export_include_original', self.include_original_checkbox.isChecked())
        settings_mgr.set_app_setting('export_multiple', self.export_multiple_checkbox.isChecked())
        settings_mgr.set_app_setting('export_folder_path', self.folder_edit.text())
        settings_mgr.set_app_setting('export_use_inout', self.use_inout_checkbox.isChecked())
        
        settings_mgr.save_app_settings()
        QMessageBox.information(self, "Settings Saved", "Export settings have been saved as defaults.")
    
    def _load_saved_settings(self):
        """Load previously saved settings"""
        if not self.parent_window or not hasattr(self.parent_window, 'settings_mgr'):
            return
        
        settings_mgr = self.parent_window.settings_mgr
        
        # Load format
        format_id = settings_mgr.get_app_setting('export_codec', 'prores')
        for i in range(self.format_combo.count()):
            if self.format_combo.itemData(i) == format_id:
                self.format_combo.setCurrentIndex(i)
                break

        # Load outputs; settings saved before outputs could be combined hold a single one
        output_types = settings_mgr.get_app_setting('export_output_types', []) or [
            settings_mgr.get_app_setting('export_output_type', 'Segmentation-Matte')]
        for output_type in output_types:
            checkbox = self.output_checkboxes.get(output_type)
            if checkbox and checkbox.isEnabled():
                checkbox.setChecked(True)

        # Load other settings
        self.use_input_folder_checkbox.setChecked(
            settings_mgr.get_app_setting('export_use_input_folder', True)
        )
        self.filename_template_edit.setText(
            settings_mgr.get_app_setting('export_filename_template', '{input_name}-{output_type}')
        )
        self.antialias_checkbox.setChecked(
            settings_mgr.get_app_setting('export_antialias', False)
        )
        self.quantizer_spin.setValue(
            settings_mgr.get_app_setting('export_quantizer', 14)
        )
        self.include_original_checkbox.setChecked(
            settings_mgr.get_app_setting('export_include_original', False)
        )
        self.export_multiple_checkbox.setChecked(
            settings_mgr.get_app_setting('export_multiple', False)
        )
        self.use_inout_checkbox.setChecked(
            settings_mgr.get_app_setting('export_use_inout', True)
        )
        
        folder_path = settings_mgr.get_app_setting('export_folder_path', '')
        if folder_path and os.path.exists(folder_path):
            self.folder_edit.setText(folder_path)
    
    # === Helper Methods ===
    
    def _get_available_object_ids(self, output_types: list) -> list:
            """Get list of available object IDs for the given outputs.
            For matting output types, reads from the matting directory on disk so
            the list reflects what was actually matted (e.g. a single combined object).
            For all other output types, reads from point_manager as usual - which
            is also what a mix of matting and other outputs is offered.
            """
            if output_types and all(t in MATTING_TYPES for t in output_types):
                return self._get_matting_object_ids()
            if self.parent_window and hasattr(self.parent_window, 'point_manager'):
                points = self.parent_window.point_manager.get_all_points()
                if points:
                    return sorted(set(point['object_id'] for point in points))
            return []
    
    def _get_matting_object_ids(self) -> list:
        """Get object IDs that have matting output on disk.
        If the user is exporting between in/out markers, only frame folders
        within that range are considered, so the result reflects what was
        actually matted in the relevant section of the video.
        """
        from sammie import core
        matting_dir = core.matting_dir
        if not os.path.exists(matting_dir):
            return []
 
        # Determine frame range to search
        in_point = None
        out_point = None
        if self.use_inout_checkbox.isChecked() and self.parent_window:
            settings_mgr = self.parent_window.settings_mgr
            in_point = settings_mgr.get_session_setting("in_point", None)
            out_point = settings_mgr.get_session_setting("out_point", None)
 
        for frame_dirname in sorted(os.listdir(matting_dir)):
            frame_dir = os.path.join(matting_dir, frame_dirname)
            if not os.path.isdir(frame_dir):
                continue
 
            # If in/out range is set, skip frames outside it
            if in_point is not None and out_point is not None:
                try:
                    frame_num = int(frame_dirname)
                    if frame_num < in_point or frame_num > out_point:
                        continue
                except ValueError:
                    continue
 
            ids = [
                int(os.path.splitext(f)[0])
                for f in os.listdir(frame_dir)
                if f.endswith('.png') and os.path.splitext(f)[0].isdigit()
            ]
            if ids:
                return sorted(ids)
        return []