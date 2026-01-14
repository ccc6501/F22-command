import os
import sys
import cv2
import numpy as np
import json
import sqlite3
from datetime import datetime
from pathlib import Path
import shutil
import uuid

# === FORCE SOFTWARE RENDERING ===
os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ["QMLSCENE_DEVICE"] = "softwarecontext"

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QFileDialog, QMessageBox,
    QPushButton, QHBoxLayout, QListWidget, QListWidgetItem, QToolButton,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QFrame, QSizePolicy,
    QScrollBar, QLabel, QInputDialog, QGraphicsPolygonItem, QGraphicsEllipseItem,
    QMenu, QSlider, QGroupBox, QComboBox, QCheckBox, QDialog, QFormLayout,
    QLineEdit, QSpinBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QTabWidget, QSplitter, QAbstractItemView
)
from PyQt6.QtGui import (
    QPixmap, QImage, QColor, QIcon, QMouseEvent, QWheelEvent, QPainter,
    QPen, QBrush, QPolygonF, QAction, QCursor
)
from PyQt6.QtCore import Qt, QSize, QPointF, pyqtSignal, QTimer

class ZoomableGraphicsView(QGraphicsView):
    """Graphics view with mouse wheel zoom and right-click drag pan."""
    
    # Signal emitted when user clicks on image (for region selection)
    imageClicked = pyqtSignal(int, int)  # x, y in image coordinates
    imageDoubleClicked = pyqtSignal(int, int)  # x, y in image coordinates
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setScene(QGraphicsScene(self))
        self.pixmap_item = None
        self.scale_factor = 1.0
        self._panning = False
        self._pan_start = QPointF()
        self.edit_mode = False  # When True, clicks edit polygon points
        self.click_handler = None  # External click handler
        self.double_click_handler = None  # External double click handler

    def set_pixmap(self, pixmap, reset_view=True):
        """Set the displayed image."""
        if self.pixmap_item:
            self.scene().removeItem(self.pixmap_item)
        self.pixmap_item = self.scene().addPixmap(pixmap)
        self.pixmap_item.setZValue(-1)  # Keep behind overlays
        if reset_view:
            self.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
            self.scale_factor = 1.0

    def wheelEvent(self, event: QWheelEvent):
        """Zoom with mouse wheel."""
        zoom_in_factor = 1.15
        zoom_out_factor = 1 / zoom_in_factor
        
        if event.angleDelta().y() > 0:
            factor = zoom_in_factor
        else:
            factor = zoom_out_factor
        
        self.scale(factor, factor)
        self.scale_factor *= factor
        event.accept()

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press: right-click for pan, left-click for selection."""
        if event.button() == Qt.MouseButton.RightButton or event.button() == Qt.MouseButton.MiddleButton:
            # Start panning
            self._panning = True
            self._pan_start = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        elif event.button() == Qt.MouseButton.LeftButton:
            # Emit click signal for region selection
            pos = self.mapToScene(event.position().toPoint())
            x, y = int(pos.x()), int(pos.y())
            self.imageClicked.emit(x, y)
            if self.click_handler:
                self.click_handler(x, y)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self.mapToScene(event.position().toPoint())
            x, y = int(pos.x()), int(pos.y())
            self.imageDoubleClicked.emit(x, y)
            if self.double_click_handler:
                self.double_click_handler(x, y)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle pan drag."""
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                int(self.horizontalScrollBar().value() - delta.x())
            )
            self.verticalScrollBar().setValue(
                int(self.verticalScrollBar().value() - delta.y())
            )
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """End panning."""
        if event.button() == Qt.MouseButton.RightButton or event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def reset_view(self):
        """Reset zoom and pan to fit image."""
        if self.pixmap_item:
            self.resetTransform()
            self.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
            self.scale_factor = 1.0


class BlueprintMapper(QMainWindow):
    def __init__(self):
        super().__init__()
        self.original_img = None
        self.processed_img = None  # Color-removed version
        self.use_processed_img = False  # Toggle for B/W mode
        self.region_map = None
        self.regions = []
        self.region_index_map = {}
        self.region_id_map = {}  # id string -> index for fast lookup
        self.image_path = ""
        self.sidebar_visible = False
        self.current_region_idx = 0  # for keyboard navigation
        
        # Zone management
        self.zones = {}  # zone_id -> {'name': str, 'color': tuple, 'visible': bool}
        self.zone_colors = [
            (255, 0, 0),    # Red
            (0, 0, 255),    # Blue
            (0, 255, 0),    # Green
            (255, 165, 0),  # Orange
            (128, 0, 128),  # Purple
            (255, 255, 0),  # Yellow
            (0, 255, 255),  # Cyan
            (255, 192, 203),# Pink
        ]
        self.active_zone_filter = None  # None = show all
        self.boundary_view = False  # When True: show regions inside selected zone boundary
        self.show_zone_boundaries = True

        # Sidebar view mode
        self.sidebar_mode = 'regions'  # 'regions' | 'zones'

        # Zone boundary edit/draw state
        self.editing_zone_id = None
        self.drawing_zone_id = None

        # Region groups
        self.groups = {}  # group_name -> set(region_id)

        # Modal state
        self._region_modal_open = False
        
        # Edit mode state
        self.edit_mode = False
        self.editing_region = None  # Region currently being edited
        self.edit_points = []  # Points for polygon editing
        self.point_items = []  # Graphics items for edit points
        
        # Drag-to-place mode
        self.drag_mode = False
        self.drag_region = None
        self.drag_offset = (0, 0)
        
        # Database connection
        self.db_path = None
        self.db_conn = None

        # Shared common folder (maps + library + shared DB)
        self.common_dir = Path.home() / "BlueprintMapperLibrary"
        (self.common_dir / "maps").mkdir(parents=True, exist_ok=True)
        (self.common_dir / "images").mkdir(parents=True, exist_ok=True)

        # Library state (when opened from library)
        self.library_image_id = None
        self.library_view_id = None
        self.library_view_rect = None  # (x,y,w,h) within original image

        # Debounced autosave
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._autosave_all)
        
        # Detection parameters (adjustable via UI)
        self.detect_params = {
            'canny_low': 30,
            'canny_high': 100,
            'close_size': 5,
            'min_area': 100,
            'invert': False,
            'remove_colors': False
        }

        # Render/view modes
        self.render_mode = 'status'  # 'status' | 'zones' | 'groups'
        self.render_filter = None  # mode-dependent; None means "all" within that mode

        self.setWindowTitle("Blueprint Mapper - Curation Mode (Zoom/Pan Enabled)")
        self.setGeometry(100, 100, 1400, 800)

        # Apply dark theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
                color: white;
            }
            QLabel {
                color: white;
                font-size: 14px;
            }
            QPushButton {
                background-color: #333;
                color: white;
                border: 1px solid #555;
                padding: 8px;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #444;
            }
            QListWidget {
                background-color: #2d2d2d;
                color: white;
                border: 1px solid #444;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 5px;
                border-bottom: 1px solid #333;
            }
            QListWidget::item:selected {
                background-color: #4a4a4a;
                color: white;
            }
        """)

        # Main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout()
        central_widget.setLayout(main_layout)

        # Left: Zoomable Image View
        self.graphics_view = ZoomableGraphicsView()
        self.graphics_view.setStyleSheet("background-color: #2d2d2d;")
        main_layout.addWidget(self.graphics_view)

        # Right: Sidebar panel (initially hidden)
        self.sidebar_panel = QWidget()
        sidebar_layout = QVBoxLayout(self.sidebar_panel)
        sidebar_layout.setContentsMargins(5, 5, 5, 5)
        
        # Zone filter dropdown
        zone_filter_layout = QHBoxLayout()
        zone_filter_label = QLabel("Zone:")
        zone_filter_label.setStyleSheet("color: white;")
        self.zone_filter_combo = QComboBox()
        self.zone_filter_combo.addItem("All Zones", None)
        self.zone_filter_combo.currentIndexChanged.connect(self.on_zone_filter_changed)
        self.zone_filter_combo.setStyleSheet("""
            QComboBox {
                background-color: #333;
                color: white;
                border: 1px solid #555;
                padding: 5px;
            }
        """)
        zone_filter_layout.addWidget(zone_filter_label)
        zone_filter_layout.addWidget(self.zone_filter_combo)
        sidebar_layout.addLayout(zone_filter_layout)

        # Zone boundary controls
        zone_controls = QHBoxLayout()
        self.boundary_view_checkbox = QCheckBox("Boundary view")
        self.boundary_view_checkbox.setToolTip("Show regions inside selected zone boundary")
        self.boundary_view_checkbox.stateChanged.connect(self.on_boundary_view_toggled)
        self.boundary_view_checkbox.setStyleSheet("color: white;")
        self.show_boundaries_checkbox = QCheckBox("Show boundaries")
        self.show_boundaries_checkbox.setToolTip("Show zone boundary outlines")
        self.show_boundaries_checkbox.setChecked(True)
        self.show_boundaries_checkbox.stateChanged.connect(self.on_show_boundaries_toggled)
        self.show_boundaries_checkbox.setStyleSheet("color: white;")
        zone_controls.addWidget(self.boundary_view_checkbox)
        zone_controls.addWidget(self.show_boundaries_checkbox)
        sidebar_layout.addLayout(zone_controls)

        # Sidebar view toggle
        sidebar_mode_layout = QHBoxLayout()
        sidebar_mode_label = QLabel("View:")
        sidebar_mode_label.setStyleSheet("color: white;")
        self.sidebar_mode_combo = QComboBox()
        self.sidebar_mode_combo.setStyleSheet("""
            QComboBox {
                background-color: #333;
                color: white;
                border: 1px solid #555;
                padding: 5px;
            }
        """)
        self.sidebar_mode_combo.addItem("Regions", 'regions')
        self.sidebar_mode_combo.addItem("Zones", 'zones')
        self.sidebar_mode_combo.currentIndexChanged.connect(self.on_sidebar_mode_changed)
        sidebar_mode_layout.addWidget(sidebar_mode_label)
        sidebar_mode_layout.addWidget(self.sidebar_mode_combo)
        sidebar_layout.addLayout(sidebar_mode_layout)

        # Render mode controls
        render_layout = QHBoxLayout()
        render_label = QLabel("Show:")
        render_label.setStyleSheet("color: white;")
        self.render_mode_combo = QComboBox()
        self.render_mode_combo.setStyleSheet("""
            QComboBox {
                background-color: #333;
                color: white;
                border: 1px solid #555;
                padding: 5px;
            }
        """)
        self.render_mode_combo.addItem("Status", 'status')
        self.render_mode_combo.addItem("Zones", 'zones')
        self.render_mode_combo.addItem("Groups", 'groups')
        self.render_mode_combo.currentIndexChanged.connect(self.on_render_mode_changed)

        self.render_filter_combo = QComboBox()
        self.render_filter_combo.setStyleSheet("""
            QComboBox {
                background-color: #333;
                color: white;
                border: 1px solid #555;
                padding: 5px;
            }
        """)
        self.render_filter_combo.currentIndexChanged.connect(self.on_render_filter_changed)

        render_layout.addWidget(render_label)
        render_layout.addWidget(self.render_mode_combo)
        render_layout.addWidget(self.render_filter_combo)
        sidebar_layout.addLayout(render_layout)

        self._refresh_render_filter_options()
        
        # Region list
        self.sidebar = QListWidget()
        self.sidebar.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.sidebar.itemClicked.connect(self.on_sidebar_item_clicked)
        self.sidebar.itemDoubleClicked.connect(self.on_sidebar_item_double_clicked)
        self.sidebar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sidebar.customContextMenuRequested.connect(self.show_region_context_menu)
        sidebar_layout.addWidget(self.sidebar)
        
        self.sidebar_panel.setVisible(False)
        main_layout.addWidget(self.sidebar_panel)

        # Add "Next" button below image
        self.next_button = QPushButton("▶ Next: Show Sidebar & Controls")
        self.next_button.clicked.connect(self.show_sidebar)
        self.next_button.setVisible(False)
        self.next_button.setStyleSheet("padding: 10px; font-size: 14px;")

        # Menu bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        open_action = file_menu.addAction("Open Image...")
        open_action.triggered.connect(self.open_image)
        save_action = file_menu.addAction("Save Mapping (Ctrl+S)")
        save_action.triggered.connect(self.save_json)
        save_action.setShortcut("Ctrl+S")
        
        # Edit menu
        edit_menu = menubar.addMenu("Edit")
        edit_region_action = edit_menu.addAction("Edit Selected Region Boundary (E)")
        edit_region_action.triggered.connect(self.start_edit_mode)
        edit_region_action.setShortcut("E")
        
        rename_region_action = edit_menu.addAction("Rename Region (F2)")
        rename_region_action.triggered.connect(self.rename_region)
        rename_region_action.setShortcut("F2")
        
        duplicate_region_action = edit_menu.addAction("Duplicate Region (Ctrl+D)")
        duplicate_region_action.triggered.connect(self.duplicate_region)
        duplicate_region_action.setShortcut("Ctrl+D")

        duplicate_opposite_action = edit_menu.addAction("Duplicate Opposite (Ctrl+Shift+D)")
        duplicate_opposite_action.triggered.connect(self.duplicate_opposite_region)
        duplicate_opposite_action.setShortcut("Ctrl+Shift+D")
        
        finish_edit_action = edit_menu.addAction("Finish Editing (Enter)")
        finish_edit_action.triggered.connect(self.finish_edit_mode)
        
        cancel_edit_action = edit_menu.addAction("Cancel Edit (Esc)")
        cancel_edit_action.triggered.connect(self.cancel_edit_mode)
        
        edit_menu.addSeparator()
        add_region_action = edit_menu.addAction("Draw New Region (N)")
        add_region_action.triggered.connect(self.start_draw_new_region)
        add_region_action.setShortcut("N")
        
        delete_region_action = edit_menu.addAction("Delete Selected Region (Del)")
        delete_region_action.triggered.connect(self.delete_selected_region)
        
        # Zone menu
        zone_menu = menubar.addMenu("Zones")
        create_zone_action = zone_menu.addAction("Create New Zone...")
        create_zone_action.triggered.connect(self.create_zone)
        
        assign_zone_action = zone_menu.addAction("Assign Region to Zone (Z)")
        assign_zone_action.triggered.connect(self.assign_region_to_zone)
        assign_zone_action.setShortcut("Z")
        
        edit_zone_action = zone_menu.addAction("Edit Zone Boundary...")
        edit_zone_action.triggered.connect(self.edit_zone_boundary)
        
        zone_menu.addSeparator()
        self.zone_filter_menu = zone_menu.addMenu("Filter by Zone")
        show_all_action = self.zone_filter_menu.addAction("Show All Zones")
        show_all_action.triggered.connect(lambda: self.set_zone_filter(None))
        
        # Database menu
        db_menu = menubar.addMenu("Database")
        connect_db_action = db_menu.addAction("Connect/Create Database...")
        connect_db_action.triggered.connect(self.connect_database)
        
        view_db_action = db_menu.addAction("View Database...")
        view_db_action.triggered.connect(self.view_database)
        
        db_menu.addSeparator()
        export_csv_action = db_menu.addAction("Export to CSV...")
        export_csv_action.triggered.connect(self.export_to_csv)
        
        import_csv_action = db_menu.addAction("Import from CSV...")
        import_csv_action.triggered.connect(self.import_from_csv)

        # Library menu
        library_menu = menubar.addMenu("Library")
        add_lib_action = library_menu.addAction("Add Image to Library...")
        add_lib_action.triggered.connect(self.add_image_to_library)
        open_lib_action = library_menu.addAction("Open Library View...")
        open_lib_action.triggered.connect(self.open_library_view)
        
        # View menu
        view_menu = menubar.addMenu("View")
        reset_view_action = view_menu.addAction("Reset Zoom (Home)")
        reset_view_action.triggered.connect(lambda: self.graphics_view.reset_view())
        reset_view_action.setShortcut("Home")
        
        redetect_action = view_menu.addAction("Re-detect Regions (F5)")
        redetect_action.triggered.connect(self.redetect_regions)
        redetect_action.setShortcut("F5")
        
        view_menu.addSeparator()
        self.toggle_bw_action = view_menu.addAction("Toggle Black/White Mode (B)")
        self.toggle_bw_action.triggered.connect(self.toggle_bw_mode)
        self.toggle_bw_action.setShortcut("B")
        self.toggle_bw_action.setCheckable(True)
        
        process_colors_action = view_menu.addAction("Remove Colors from Image...")
        process_colors_action.triggered.connect(self.remove_colors_from_image)

        # Add button layout with next button and status label
        button_layout = QVBoxLayout()
        button_layout.addWidget(self.next_button)
        
        # Status label for progress
        self.status_label = QLabel("No image loaded")
        self.status_label.setStyleSheet("color: #aaa; padding: 5px;")
        button_layout.addWidget(self.status_label)
        
        main_layout.addLayout(button_layout)

        # Ensure zone UI starts clean
        self.refresh_zone_ui()

        # Auto-connect shared DB in common folder
        self._connect_default_database()

        print("✅ Application started. Main window ready.")

    def open_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Blueprint",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not file_path:
            return

        try:
            self.load_and_process(file_path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed:\n{str(e)}")
            raise

    def load_and_process(self, path):
        print(f"Loading image: {path}")
        img = cv2.imread(path)
        if img is None:
            raise ValueError("OpenCV could not read the image. Try a different format or path.")

        self.original_img = img
        self.image_path = path
        
        # Detect regions with current parameters
        self.detect_regions()
        
    def detect_regions(self):
        """Multi-strategy region detection that handles various image types."""
        if self.original_img is None:
            return
            
        img = self.original_img
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        
        # Determine if image is dark or light background
        mean_brightness = np.mean(gray)
        is_dark_bg = mean_brightness < 128
        print(f"Image analysis: mean brightness={mean_brightness:.1f}, dark_bg={is_dark_bg}")
        
        params = self.detect_params
        all_contours = []
        
        # === Strategy 1: Edge-based detection (good for line drawings) ===
        edges = cv2.Canny(gray, params['canny_low'], params['canny_high'])
        
        # Dilate to close small gaps
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges_dilated = cv2.dilate(edges, kernel, iterations=2)
        
        # Close to seal gaps
        close_k = cv2.getStructuringElement(cv2.MORPH_RECT, 
                                             (params['close_size'], params['close_size']))
        edges_closed = cv2.morphologyEx(edges_dilated, cv2.MORPH_CLOSE, close_k, iterations=2)
        
        # Flood fill from corners to find background
        flood = edges_closed.copy()
        mask = np.zeros((h + 2, w + 2), np.uint8)
        # Fill from all corners
        for corner in [(0, 0), (w-1, 0), (0, h-1), (w-1, h-1)]:
            cv2.floodFill(flood, mask.copy(), corner, 255)
        
        enclosed = cv2.bitwise_not(flood)
        edge_contours, _ = cv2.findContours(enclosed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        all_contours.extend(edge_contours)
        print(f"  Edge detection found {len(edge_contours)} contours")
        
        # === Strategy 2: Threshold-based (good for solid regions) ===
        if is_dark_bg:
            # Light lines on dark background
            _, binary = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY)
        else:
            # Dark lines on light background
            _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
        
        if params['invert']:
            binary = cv2.bitwise_not(binary)
            
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, close_k, iterations=1)
        thresh_contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        all_contours.extend(thresh_contours)
        print(f"  Threshold detection found {len(thresh_contours)} contours")
        
        # === Strategy 3: Adaptive threshold (good for varying lighting) ===
        adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                          cv2.THRESH_BINARY_INV, 21, 5)
        adaptive = cv2.morphologyEx(adaptive, cv2.MORPH_CLOSE, kernel, iterations=1)
        adapt_contours, _ = cv2.findContours(adaptive, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        all_contours.extend(adapt_contours)
        print(f"  Adaptive threshold found {len(adapt_contours)} contours")
        
        # === Strategy 4: Color segmentation (good for colored regions) ===
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        # Find distinct color regions
        for hue_center in [0, 30, 60, 90, 120, 150]:
            lower = np.array([max(0, hue_center - 15), 50, 50])
            upper = np.array([min(180, hue_center + 15), 255, 255])
            mask_color = cv2.inRange(hsv, lower, upper)
            if np.sum(mask_color) > 1000:  # Only if significant area
                color_contours, _ = cv2.findContours(mask_color, cv2.RETR_EXTERNAL, 
                                                      cv2.CHAIN_APPROX_SIMPLE)
                all_contours.extend(color_contours)
        
        # === Strategy 5: Watershed for nested/overlapping regions ===
        # Find sure background and foreground
        sure_bg = cv2.dilate(edges_closed, kernel, iterations=3)
        dist_transform = cv2.distanceTransform(cv2.bitwise_not(edges_closed), cv2.DIST_L2, 5)
        _, sure_fg = cv2.threshold(dist_transform, 0.3 * dist_transform.max(), 255, 0)
        sure_fg = np.uint8(sure_fg)
        
        # Find unknown region and apply watershed
        unknown = cv2.subtract(sure_bg, sure_fg)
        _, markers = cv2.connectedComponents(sure_fg)
        markers = markers + 1
        markers[unknown == 255] = 0
        
        try:
            markers = cv2.watershed(img, markers)
            # Extract contours from watershed regions
            for marker_id in range(2, markers.max() + 1):
                region_mask = np.uint8(markers == marker_id) * 255
                ws_contours, _ = cv2.findContours(region_mask, cv2.RETR_EXTERNAL, 
                                                   cv2.CHAIN_APPROX_SIMPLE)
                all_contours.extend(ws_contours)
        except:
            pass  # Watershed can fail on some images
        
        print(f"  Total contours before filtering: {len(all_contours)}")
        
        # === Filter and deduplicate contours ===
        min_area = params['min_area']
        max_area = h * w * 0.85
        
        self.regions = []
        self.region_map = np.zeros_like(gray, dtype=np.int32)
        self.region_index_map = {}
        self.region_id_map = {}
        
        used_centroids = set()
        region_counter = 0
        
        for cnt in all_contours:
            area = cv2.contourArea(cnt)
            if area < min_area or area > max_area:
                continue
            
            # Get centroid
            M = cv2.moments(cnt)
            if M['m00'] != 0:
                cx = int(M['m10'] / M['m00'])
                cy = int(M['m01'] / M['m00'])
            else:
                x, y, bw, bh = cv2.boundingRect(cnt)
                cx, cy = x + bw // 2, y + bh // 2
            
            # Deduplicate by centroid proximity (5px)
            centroid_key = (cx // 5, cy // 5)
            if centroid_key in used_centroids:
                continue
            used_centroids.add(centroid_key)
            
            # Simplify contour slightly
            epsilon = 0.002 * cv2.arcLength(cnt, True)
            cnt = cv2.approxPolyDP(cnt, epsilon, True)
            
            region_counter += 1
            region_id = region_counter
            
            region_data = {
                'id': f'region_{region_id:03d}',
                'contour': cnt,
                'area': area,
                'center': (cx, cy),
                'bbox': cv2.boundingRect(cnt),
                'status': 'pending'
            }
            self.regions.append(region_data)
            idx = len(self.regions) - 1
            self.region_index_map[region_id] = idx
            self.region_id_map[region_data['id']] = idx
            cv2.drawContours(self.region_map, [cnt], -1, region_id, cv2.FILLED)
        
        # Sort by area (largest first)
        self.regions.sort(key=lambda r: r['area'], reverse=True)
        self.region_id_map = {r['id']: i for i, r in enumerate(self.regions)}

        # Ensure region_map and index mapping match sorted order
        self.rebuild_region_map()
        
        print(f"✅ Detected {len(self.regions)} unique regions.")
        self.update_status()
        self.show_all_regions_labeled()
        self.next_button.setVisible(True)
    
    def redetect_regions(self):
        """Re-run detection with current parameters."""
        if self.original_img is None:
            QMessageBox.warning(self, "No Image", "Please load an image first.")
            return
        self.detect_regions()

    def show_all_regions_labeled(self):
        base_img = self.processed_img if self.use_processed_img else self.original_img
        overlay = base_img.copy()
        
        # Get visible regions based on zone filter + render mode/filter
        visible_regions = self.get_draw_regions()

        for region in visible_regions:
            fill_color, border_color = self._style_for_region(region)
            # Fill region
            cv2.drawContours(overlay, [region['contour']], -1, fill_color, thickness=cv2.FILLED)
            # Outline
            cv2.drawContours(overlay, [region['contour']], -1, border_color, thickness=2)
            # Add label text (place above bbox so it doesn't block region)
            display_name = region.get('name', region['id'])
            text = display_name
            font = cv2.FONT_HERSHEY_SIMPLEX
            scale = 0.4
            thickness = 1
            (text_w, text_h), _ = cv2.getTextSize(text, font, scale, thickness)
            bx, by, bw, bh = region.get('bbox', (region['center'][0], region['center'][1], 0, 0))
            text_x = int(min(max(0, bx), overlay.shape[1] - text_w - 6))
            text_y = int(max(text_h + 6, by - 6))
            cv2.rectangle(
                overlay,
                (text_x - 4, text_y - text_h - 6),
                (text_x + text_w + 4, text_y + 4),
                (0, 0, 0),
                cv2.FILLED,
            )
            cv2.rectangle(
                overlay,
                (text_x - 4, text_y - text_h - 6),
                (text_x + text_w + 4, text_y + 4),
                (255, 255, 255),
                1,
            )
            cv2.putText(overlay, text, (text_x, text_y), font, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
            cv2.putText(overlay, text, (text_x, text_y), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)

        # Draw zone outlines (if defined)
        if self.show_zone_boundaries:
            self._draw_zone_boundaries(overlay)

        final = cv2.addWeighted(overlay, 0.3, base_img, 0.7, 0)
        h, w = final.shape[:2]
        qimg = QImage(final.data, w, h, w*3, QImage.Format.Format_BGR888)
        pixmap = QPixmap.fromImage(qimg)
        self.graphics_view.set_pixmap(pixmap)

        print(f"🖼️ {len(visible_regions)} regions labeled and displayed. Click 'Next' to show sidebar.")

    def show_sidebar(self):
        if self.sidebar_mode == 'zones':
            self.show_zones_sidebar()
            return

        # Ensure region sidebar handlers are connected
        try:
            self.sidebar.itemClicked.disconnect()
        except Exception:
            pass
        try:
            self.sidebar.itemDoubleClicked.disconnect()
        except Exception:
            pass
        self.sidebar.itemClicked.connect(self.on_sidebar_item_clicked)
        self.sidebar.itemDoubleClicked.connect(self.on_sidebar_item_double_clicked)

        # Clear all highlights (reset to original image)
        img = self.processed_img if self.use_processed_img else self.original_img
        h, w = img.shape[:2]
        qimg = QImage(img.data, w, h, w*3, QImage.Format.Format_BGR888)
        pixmap = QPixmap.fromImage(qimg)
        self.graphics_view.set_pixmap(pixmap, reset_view=False)

        # Populate sidebar with approve/reject controls
        self.sidebar.clear()
        
        # Filter regions by zone/boundary + render view/filter; sort top-to-bottom
        visible_regions = self.get_draw_regions()
        
        for region in visible_regions:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, region['id'])  # Store ID for lookup

            if region.get('status') == 'rejected':
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)

            # Create widget for item
            widget = QWidget()
            layout = QHBoxLayout()
            layout.setContentsMargins(5, 5, 5, 5)

            # Region ID label with zone prefix if applicable
            display_name = region.get('name', region['id'])
            zone_id = region.get('zone')
            if zone_id and zone_id in self.zones:
                zone_info = self.zones[zone_id]
                label = QLabel(f"[{zone_info['name']}] {display_name}")
                # Color code by zone
                r, g, b = zone_info['color']
                label.setStyleSheet(f"color: rgb({r},{g},{b}); font-weight: bold;")
            else:
                label = QLabel(display_name)
                label.setStyleSheet("color: white; font-weight: bold;")

            if region.get('status') == 'rejected':
                label.setStyleSheet("color: #777; font-weight: bold;")
            layout.addWidget(label)

            # Approve button
            approve_btn = QToolButton()
            approve_btn.setText("✅")
            approve_btn.setToolTip("Approve this region")
            approve_btn.setFixedSize(30, 30)
            approve_btn.setStyleSheet("""
                QToolButton {
                    background-color: #28a745;
                    color: white;
                    border: none;
                    border-radius: 15px;
                }
                QToolButton:hover {
                    background-color: #218838;
                }
            """)
            approve_btn.clicked.connect(lambda checked, r=region: self.approve_region(r))
            layout.addWidget(approve_btn)

            # Reject button
            reject_btn = QToolButton()
            reject_btn.setText("❌")
            reject_btn.setToolTip("Reject this region")
            reject_btn.setFixedSize(30, 30)
            reject_btn.setStyleSheet("""
                QToolButton {
                    background-color: #dc3545;
                    color: white;
                    border: none;
                    border-radius: 15px;
                }
                QToolButton:hover {
                    background-color: #c82333;
                }
            """)
            reject_btn.clicked.connect(lambda checked, r=region: self.reject_region(r))
            layout.addWidget(reject_btn)

            widget.setLayout(layout)
            item.setSizeHint(widget.sizeHint())
            self.sidebar.addItem(item)
            self.sidebar.setItemWidget(item, widget)

        # Show sidebar panel
        self.sidebar_panel.setVisible(True)
        self.next_button.setText("◀ Back to Labeled View")
        self.next_button.clicked.disconnect()
        self.next_button.clicked.connect(self.back_to_labeled_view)

        # Connect image click to region selection
        self.graphics_view.click_handler = self.handle_image_click
        self.graphics_view.double_click_handler = self.handle_image_double_click

        print(f"📋 Sidebar shown with {len(visible_regions)} regions. Click any region to sync highlight.")

    def show_zones_sidebar(self):
        if self.original_img is None:
            return

        # Reset image
        img = self.processed_img if self.use_processed_img else self.original_img
        overlay = img.copy()
        if self.show_zone_boundaries:
            self._draw_zone_boundaries(overlay)
        out = cv2.addWeighted(overlay, 0.35, img, 0.65, 0)
        h, w = out.shape[:2]
        qimg = QImage(out.data, w, h, w * 3, QImage.Format.Format_BGR888)
        pixmap = QPixmap.fromImage(qimg)
        self.graphics_view.set_pixmap(pixmap, reset_view=False)

        self.sidebar.clear()
        for zid, zinfo in self.zones.items():
            item = QListWidgetItem(zinfo.get('name', str(zid)))
            item.setData(Qt.ItemDataRole.UserRole, zid)
            self.sidebar.addItem(item)

        # Click selects zone filter; double-click edits/draws boundary
        def on_click(item):
            zid = item.data(Qt.ItemDataRole.UserRole)
            self.active_zone_filter = zid
            if hasattr(self, 'zone_filter_combo'):
                idx = self.zone_filter_combo.findData(zid)
                if idx >= 0:
                    self.zone_filter_combo.setCurrentIndex(idx)
            self.refresh_image_with_status()

        def on_double(item):
            zid = item.data(Qt.ItemDataRole.UserRole)
            if zid is None or zid not in self.zones:
                return
            if self.zones[zid].get('contour') is None:
                self.start_draw_zone(zid)
            else:
                self.start_edit_zone(zid)

        try:
            self.sidebar.itemClicked.disconnect()
        except Exception:
            pass
        try:
            self.sidebar.itemDoubleClicked.disconnect()
        except Exception:
            pass
        self.sidebar.itemClicked.connect(on_click)
        self.sidebar.itemDoubleClicked.connect(on_double)

        self.sidebar_panel.setVisible(True)
        self.next_button.setText("◀ Back to Labeled View")
        self.next_button.clicked.disconnect()
        self.next_button.clicked.connect(self.back_to_labeled_view)

        # In zone view, keep region click handlers disabled
        self.graphics_view.click_handler = None
        self.graphics_view.double_click_handler = None

    def back_to_labeled_view(self):
        self.show_all_regions_labeled()
        self.sidebar_panel.setVisible(False)
        self.next_button.setText("▶ Next: Show Sidebar & Controls")
        self.next_button.clicked.disconnect()
        self.next_button.clicked.connect(self.show_sidebar)

        # Clear click handler
        self.graphics_view.click_handler = None
        self.graphics_view.double_click_handler = None

        # Restore region sidebar handlers
        try:
            self.sidebar.itemClicked.disconnect()
        except Exception:
            pass
        try:
            self.sidebar.itemDoubleClicked.disconnect()
        except Exception:
            pass
        self.sidebar.itemClicked.connect(self.on_sidebar_item_clicked)
        self.sidebar.itemDoubleClicked.connect(self.on_sidebar_item_double_clicked)

    def on_sidebar_mode_changed(self):
        self.sidebar_mode = self.sidebar_mode_combo.currentData() or 'regions'
        if self.original_img is None:
            return
        if self.sidebar_panel.isVisible():
            self.show_sidebar()
            self.refresh_image_with_status()

    def handle_image_click(self, x, y):
        """Handle click on image to select region."""
        if self.original_img is None:
            return
        
        H, W = self.original_img.shape[:2]
        if not (0 <= x < W and 0 <= y < H):
            return
        
        rid = int(self.region_map[y, x])
        if rid == 0:
            return
        
        idx = self.region_index_map.get(rid)
        if idx is None:
            print(f"Clicked region id {rid} has no mapping; ignoring.")
            return
        
        region = self.regions[idx]
        if region.get('status') == 'rejected':
            return
        self.highlight_region(region)
        
        # Scroll sidebar to this region
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == region['id']:
                self.sidebar.setCurrentItem(item)
                self.sidebar.scrollToItem(item)
                break

    def handle_image_double_click(self, x, y):
        if self.original_img is None:
            return
        H, W = self.original_img.shape[:2]
        if not (0 <= x < W and 0 <= y < H):
            return
        rid = int(self.region_map[y, x])
        if rid == 0:
            return
        idx = self.region_index_map.get(rid)
        if idx is None:
            return
        region = self.regions[idx]
        if region.get('status') == 'rejected':
            return
        self.highlight_region(region)
        self._select_sidebar_region_by_id(region['id'])
        self.open_region_modal(region)
    
    def highlight_region(self, region):
        """Highlight a single region on the image."""
        base_img = self.processed_img if self.use_processed_img else self.original_img
        overlay = base_img.copy()

        fill_color, border_color = self._style_for_region(region)
        cv2.drawContours(overlay, [region['contour']], -1, fill_color, thickness=cv2.FILLED)
        out = cv2.addWeighted(overlay, 0.25, base_img, 0.75, 0)
        cv2.drawContours(out, [region['contour']], -1, border_color, thickness=4)
        
        # Draw label (place above bbox so it doesn't block region)
        display_name = region.get('name', region['id'])
        text = display_name
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.7
        thickness = 2
        (text_w, text_h), _ = cv2.getTextSize(text, font, scale, thickness)
        bx, by, bw, bh = region.get('bbox', (region['center'][0], region['center'][1], 0, 0))
        text_x = int(min(max(0, bx), overlay.shape[1] - text_w - 10))
        text_y = int(max(text_h + 10, by - 10))
        cv2.rectangle(
            out,
            (text_x - 6, text_y - text_h - 10),
            (text_x + text_w + 6, text_y + 6),
            (0, 0, 0),
            cv2.FILLED,
        )
        cv2.rectangle(
            out,
            (text_x - 6, text_y - text_h - 10),
            (text_x + text_w + 6, text_y + 6),
            (255, 255, 255),
            2,
        )
        cv2.putText(out, text, (text_x, text_y), font, scale, (0, 0, 0), thickness + 3, cv2.LINE_AA)
        cv2.putText(out, text, (text_x, text_y), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)
        
        # Keep boundaries visible if enabled
        if self.show_zone_boundaries:
            self._draw_zone_boundaries(out)
        h, w = out.shape[:2]
        qimg = QImage(out.data, w, h, w * 3, QImage.Format.Format_BGR888)
        pixmap = QPixmap.fromImage(qimg)
        self.graphics_view.set_pixmap(pixmap, reset_view=False)
        
        print(f"Selected: {display_name}")

    def on_sidebar_item_clicked(self, item):
        region_id = item.data(Qt.ItemDataRole.UserRole)
        
        # Find region by ID
        idx = self.region_id_map.get(region_id)
        if idx is None:
            return
        
        region = self.regions[idx]
        if region.get('status') == 'rejected':
            return
        self.highlight_region(region)

    def on_sidebar_item_double_clicked(self, item):
        region_id = item.data(Qt.ItemDataRole.UserRole)
        idx = self.region_id_map.get(region_id)
        if idx is None:
            return
        region = self.regions[idx]
        if region.get('status') == 'rejected':
            return
        self.highlight_region(region)
        self.open_region_modal(region)

    def _select_sidebar_region_by_id(self, region_id: str) -> bool:
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == region_id:
                self.sidebar.setCurrentItem(item)
                self.sidebar.scrollToItem(item)
                return True
        return False

    def _update_sidebar_item_label(self, region_id: str):
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item.data(Qt.ItemDataRole.UserRole) != region_id:
                continue
            widget = self.sidebar.itemWidget(item)
            if not widget:
                return
            name_label = widget.layout().itemAt(0).widget()
            if isinstance(name_label, QLabel):
                idx = self.region_id_map.get(region_id)
                if idx is None:
                    return
                region = self.regions[idx]
                name_label.setText(region.get('name', region['id']))
            return

    def open_region_modal(self, region):
        if self._region_modal_open:
            return
        self._region_modal_open = True

        try:
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Region: {region.get('name', region['id'])}")
            dialog.setModal(True)
            dialog.setMinimumWidth(420)

            layout = QVBoxLayout(dialog)
            form = QFormLayout()

            id_label = QLabel(region['id'])
            id_label.setStyleSheet("color: white;")
            form.addRow("ID:", id_label)

            status_label = QLabel(region.get('status', 'pending'))
            status_label.setStyleSheet("color: white;")
            form.addRow("Status:", status_label)

            name_edit = QLineEdit(region.get('name', region['id']))
            name_edit.setStyleSheet("background-color: #333; color: white; border: 1px solid #555; padding: 4px;")
            form.addRow("Name:", name_edit)

            zone_combo = QComboBox()
            zone_combo.setStyleSheet("background-color: #333; color: white; border: 1px solid #555; padding: 4px;")
            zone_combo.addItem("(None)", None)
            for zid, z in self.zones.items():
                zone_combo.addItem(z.get('name', zid), zid)
            current_zone = region.get('zone')
            if current_zone is None:
                zone_combo.setCurrentIndex(0)
            else:
                for i in range(zone_combo.count()):
                    if zone_combo.itemData(i) == current_zone:
                        zone_combo.setCurrentIndex(i)
                        break
            form.addRow("Zone:", zone_combo)

            group_combo = QComboBox()
            group_combo.setStyleSheet("background-color: #333; color: white; border: 1px solid #555; padding: 4px;")
            group_combo.addItem("(None)", None)
            group_combo.addItem("+ New Group...", "__NEW__")
            for gname in sorted(self.groups.keys()):
                group_combo.addItem(gname, gname)
            current_group = region.get('group')
            if current_group is None:
                group_combo.setCurrentIndex(0)
            else:
                for i in range(group_combo.count()):
                    if group_combo.itemData(i) == current_group:
                        group_combo.setCurrentIndex(i)
                        break
            form.addRow("Group:", group_combo)

            layout.addLayout(form)

            button_row = QHBoxLayout()
            approve_btn = QPushButton("Approve")
            approve_btn.setStyleSheet("padding: 8px; background-color: #28a745; color: white; border: none;")
            reject_btn = QPushButton("Reject")
            reject_btn.setStyleSheet("padding: 8px; background-color: #dc3545; color: white; border: none;")
            edit_btn = QPushButton("Edit Boundary")
            edit_btn.setStyleSheet("padding: 8px;")
            dup_btn = QPushButton("Duplicate")
            dup_btn.setStyleSheet("padding: 8px;")
            dup_opp_btn = QPushButton("Duplicate Opposite")
            dup_opp_btn.setStyleSheet("padding: 8px;")
            apply_btn = QPushButton("Apply")
            apply_btn.setStyleSheet("padding: 8px; background-color: #0078d4; color: white; border: none;")
            close_btn = QPushButton("Close")
            close_btn.setStyleSheet("padding: 8px;")

            button_row.addWidget(approve_btn)
            button_row.addWidget(reject_btn)
            button_row.addWidget(edit_btn)
            button_row.addWidget(dup_btn)
            button_row.addWidget(dup_opp_btn)
            button_row.addWidget(apply_btn)
            button_row.addWidget(close_btn)
            layout.addLayout(button_row)

            def apply_changes():
                new_name = name_edit.text().strip()
                if new_name:
                    region['name'] = new_name

                selected_zone = zone_combo.currentData()
                region['zone'] = selected_zone

                selected_group = group_combo.currentData()
                if selected_group == "__NEW__":
                    gname, ok = QInputDialog.getText(dialog, "New Group", "Group name:")
                    if ok:
                        gname = gname.strip()
                        if gname:
                            selected_group = gname
                            self.groups.setdefault(gname, set())
                            if group_combo.findData(gname) == -1:
                                group_combo.addItem(gname, gname)
                            for i in range(group_combo.count()):
                                if group_combo.itemData(i) == gname:
                                    group_combo.setCurrentIndex(i)
                                    break
                        else:
                            selected_group = None
                    else:
                        selected_group = region.get('group')

                old_group = region.get('group')
                if old_group and old_group in self.groups:
                    self.groups[old_group].discard(region['id'])
                    if not self.groups[old_group]:
                        del self.groups[old_group]

                if selected_group is None:
                    region['group'] = None
                else:
                    region['group'] = selected_group
                    self.groups.setdefault(selected_group, set()).add(region['id'])

                dialog.setWindowTitle(f"Region: {region.get('name', region['id'])}")
                status_label.setText(region.get('status', 'pending'))
                self._update_sidebar_item_label(region['id'])
                self._refresh_render_filter_options()
                self.refresh_image_with_status()

            def do_approve():
                self._select_sidebar_region_by_id(region['id'])
                self.approve_region(region)
                dialog.accept()

            def do_reject():
                self._select_sidebar_region_by_id(region['id'])
                self.reject_region(region)
                dialog.accept()

            def do_edit_boundary():
                self._select_sidebar_region_by_id(region['id'])
                self.start_edit_mode()
                dialog.accept()

            def do_duplicate():
                self._select_sidebar_region_by_id(region['id'])
                self.duplicate_region()
                dialog.accept()

            def do_duplicate_opposite():
                self._select_sidebar_region_by_id(region['id'])
                self.duplicate_opposite_region()
                dialog.accept()

            approve_btn.clicked.connect(do_approve)
            reject_btn.clicked.connect(do_reject)
            edit_btn.clicked.connect(do_edit_boundary)
            dup_btn.clicked.connect(do_duplicate)
            dup_opp_btn.clicked.connect(do_duplicate_opposite)
            apply_btn.clicked.connect(apply_changes)
            close_btn.clicked.connect(dialog.reject)

            dialog.exec()
        finally:
            self._region_modal_open = False

    def approve_region(self, region):
        region['status'] = 'approved'
        print(f"✅ Approved: {region['id']}")
        self.update_sidebar_status(region['id'], 'approved')
        self.update_status()
        self._upsert_region_to_db(region)
        self.schedule_autosave()
        self.refresh_image_with_status()

    def reject_region(self, region):
        region['status'] = 'rejected'
        print(f"❌ Rejected: {region['id']}")
        self.update_sidebar_status(region['id'], 'rejected')
        self.update_status()
        self.schedule_autosave()
        self.refresh_image_with_status()

    def schedule_autosave(self):
        # debounce frequent edits
        if hasattr(self, '_autosave_timer'):
            self._autosave_timer.start(500)

    def _mapping_output_path(self):
        stem = Path(self.image_path).stem if self.image_path else "untitled"
        if self.library_view_id:
            stem = f"{stem}__view_{self.library_view_id[:8]}"
        return self.common_dir / "maps" / f"{stem}_regions.json"

    def _serialize_regions_payload(self):
        def contour_to_list(cnt):
            return [[int(p[0][0]), int(p[0][1])] for p in cnt]

        def zone_contour_to_list(cnt):
            if cnt is None:
                return None
            return [[int(p[0][0]), int(p[0][1])] for p in cnt]

        payload = {
            "image_path": self.image_path,
            "library_image_id": self.library_image_id,
            "library_view_id": self.library_view_id,
            "library_view_rect": list(self.library_view_rect) if self.library_view_rect else None,
            "saved_at": datetime.utcnow().isoformat(),
            "regions": [],
            "zones": [],
            "groups": {},
        }
        for r in self.regions:
            payload["regions"].append({
                "id": r.get('id'),
                "name": r.get('name', r.get('id')),
                "status": r.get('status', 'pending'),
                "zone": r.get('zone'),
                "group": r.get('group'),
                "center": [int(r['center'][0]), int(r['center'][1])],
                "bbox": list(r.get('bbox', (0, 0, 0, 0))),
                "contour": contour_to_list(r['contour']),
            })

        # Zones (include boundaries if present)
        for zid, zinfo in self.zones.items():
            payload["zones"].append({
                "id": zid,
                "name": zinfo.get('name', str(zid)),
                "color": list(zinfo.get('color', (255, 255, 255))),
                "visible": bool(zinfo.get('visible', True)),
                "contour": zone_contour_to_list(zinfo.get('contour')),
            })

        # Groups
        try:
            payload["groups"] = {g: sorted(list(ids)) for g, ids in self.groups.items()}
        except Exception:
            payload["groups"] = {}
        return payload

    def _autosave_all(self):
        if self.original_img is None:
            return
        out_path = self._mapping_output_path()
        try:
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(self._serialize_regions_payload(), f, indent=2)
        except Exception as e:
            print(f"⚠️ Autosave failed: {e}")
            return

        if self.db_conn:
            try:
                if self.library_view_id:
                    self._upsert_view_map_to_db()
                    self._upsert_view_regions_to_db()
                self.db_conn.commit()
            except Exception:
                pass

    def _upsert_view_map_to_db(self):
        if not self.db_conn or not self.library_view_id:
            return
        cur = self.db_conn.cursor()
        cur.execute(
            """
            INSERT INTO view_maps (view_id, map_json, updated_at)
            VALUES (?,?,?)
            ON CONFLICT(view_id) DO UPDATE SET
                map_json=excluded.map_json,
                updated_at=excluded.updated_at
            """,
            (
                self.library_view_id,
                json.dumps(self._serialize_regions_payload()),
                datetime.utcnow().isoformat(),
            ),
        )

    def _upsert_view_regions_to_db(self):
        if not self.db_conn or not self.library_view_id:
            return
        cur = self.db_conn.cursor()
        view_id = self.library_view_id

        # Replace all rows for the view (keeps DB consistent with current in-memory map)
        cur.execute("DELETE FROM view_regions WHERE view_id=?", (view_id,))

        def contour_to_json(cnt):
            pts = [[int(p[0][0]), int(p[0][1])] for p in cnt]
            return json.dumps(pts)

        for r in self.regions:
            cur.execute(
                """
                INSERT INTO view_regions (
                    view_id, region_id, name, status, zone, group_name,
                    contour_json, bbox_json, center_x, center_y, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    view_id,
                    r.get('id'),
                    r.get('name', r.get('id')),
                    r.get('status', 'pending'),
                    None if r.get('zone') is None else str(r.get('zone')),
                    r.get('group'),
                    contour_to_json(r['contour']),
                    json.dumps(list(r.get('bbox', (0, 0, 0, 0)))),
                    int(r['center'][0]),
                    int(r['center'][1]),
                    datetime.utcnow().isoformat(),
                ),
            )

    def _load_view_map_from_db(self, view_id):
        if not self.db_conn or not view_id:
            return False
        try:
            cur = self.db_conn.cursor()
            row = cur.execute("SELECT map_json FROM view_maps WHERE view_id=?", (view_id,)).fetchone()
            if not row or not row[0]:
                return False
            payload = json.loads(row[0])
        except Exception:
            return False

        # Restore groups
        self.groups = {}
        try:
            for g, ids in (payload.get('groups') or {}).items():
                self.groups[g] = set(ids or [])
        except Exception:
            self.groups = {}

        # Restore zones
        self.zones = {}
        for z in payload.get('zones') or []:
            zid = z.get('id')
            contour = None
            pts = z.get('contour')
            if pts and isinstance(pts, list) and len(pts) >= 3:
                contour = np.array(pts, dtype=np.int32).reshape(-1, 1, 2)
            color = z.get('color') or [255, 255, 255]
            try:
                color = (int(color[0]), int(color[1]), int(color[2]))
            except Exception:
                color = (255, 255, 255)
            self.zones[zid] = {
                'name': z.get('name', str(zid)),
                'color': color,
                'visible': bool(z.get('visible', True)),
                'contour': contour,
            }

        # Restore regions
        regions = []
        for r in payload.get('regions') or []:
            pts = r.get('contour') or []
            if not pts or len(pts) < 3:
                continue
            cnt = np.array(pts, dtype=np.int32).reshape(-1, 1, 2)
            bbox = r.get('bbox') or [0, 0, 0, 0]
            center = r.get('center') or [0, 0]
            try:
                area = float(cv2.contourArea(cnt))
            except Exception:
                area = 0.0
            regions.append({
                'id': r.get('id'),
                'name': r.get('name', r.get('id')),
                'status': r.get('status', 'pending'),
                'zone': r.get('zone'),
                'group': r.get('group'),
                'contour': cnt,
                'bbox': tuple(bbox) if isinstance(bbox, (list, tuple)) and len(bbox) == 4 else (0, 0, 0, 0),
                'center': (int(center[0]), int(center[1])) if isinstance(center, (list, tuple)) and len(center) == 2 else (0, 0),
                'area': area,
            })

        self.regions = regions
        self.region_id_map = {r['id']: i for i, r in enumerate(self.regions) if r.get('id')}
        self.rebuild_region_map()
        self._refresh_render_filter_options()
        self.refresh_zone_ui()
        self.update_status()
        return True

    def _zone_to_int(self, zone_id):
        if zone_id is None:
            return None
        s = str(zone_id)
        digits = ''.join(ch for ch in s if ch.isdigit())
        if not digits:
            return None
        try:
            return int(digits)
        except Exception:
            return None

    def _upsert_region_to_db(self, region):
        """Upsert approved region to the inventory table (regions)."""
        if not self.db_conn:
            return
        try:
            cur = self.db_conn.cursor()
            cur.execute("""
                INSERT INTO regions (region_id, name, zone, updated_at)
                VALUES (?,?,?,?)
                ON CONFLICT(region_id) DO UPDATE SET
                    name=excluded.name,
                    zone=excluded.zone,
                    updated_at=excluded.updated_at
            """, (
                region.get('id'),
                region.get('name', region.get('id')),
                self._zone_to_int(region.get('zone')),
                datetime.utcnow().isoformat(),
            ))
        except Exception as e:
            print(f"⚠️ DB upsert failed: {e}")

    def update_status(self):
        """Update the status label with approval progress."""
        if not self.regions:
            self.status_label.setText("No image loaded")
            return
        approved = sum(1 for r in self.regions if r['status'] == 'approved')
        rejected = sum(1 for r in self.regions if r['status'] == 'rejected')
        pending = len(self.regions) - approved - rejected
        self.status_label.setText(
            f"✅ {approved}  ❌ {rejected}  ⏳ {pending}  |  Total: {len(self.regions)}"
        )

    def refresh_image_with_status(self):
        """Redraw image using current render mode/filter colors."""
        if self.original_img is None:
            return
        base_img = self.processed_img if self.use_processed_img else self.original_img
        overlay = base_img.copy()

        regions = self.get_draw_regions()
        for region in regions:
            fill_color, _ = self._style_for_region(region)
            cv2.drawContours(overlay, [region['contour']], -1, fill_color, thickness=cv2.FILLED)

        out = cv2.addWeighted(overlay, 0.25, base_img, 0.75, 0)

        # Neon borders after blend
        for region in regions:
            _, border_color = self._style_for_region(region)
            cv2.drawContours(out, [region['contour']], -1, border_color, thickness=3)

        if self.show_zone_boundaries:
            self._draw_zone_boundaries(out)
        h, w = out.shape[:2]
        qimg = QImage(out.data, w, h, w * 3, QImage.Format.Format_BGR888)
        pixmap = QPixmap.fromImage(qimg)
        self.graphics_view.set_pixmap(pixmap, reset_view=False)

    def _draw_zone_boundaries(self, img):
        """Draw zone boundary polylines onto img (in-place)."""
        # Neon blue (BGR) for zone boundaries
        boundary_color = (255, 0, 0)
        for zid, zinfo in self.zones.items():
            if self.active_zone_filter is not None and zid != self.active_zone_filter:
                continue
            zcnt = zinfo.get('contour')
            if zcnt is None:
                continue
            cv2.polylines(img, [zcnt], True, boundary_color, 2)

    def _style_for_region(self, region):
        """Return (fill_bgr, border_bgr) using neon palette based on current mode."""
        neon_yellow = (0, 255, 255)
        neon_green = (0, 255, 0)
        neon_red = (0, 0, 255)
        neon_blue = (255, 0, 0)
        neon_pink = (255, 0, 255)

        if self.render_mode == 'zones':
            return neon_blue, neon_blue
        if self.render_mode == 'groups':
            return neon_pink, neon_pink

        status = region.get('status', 'pending')
        if status == 'approved':
            return neon_green, neon_green
        if status == 'rejected':
            return neon_red, neon_red
        return neon_yellow, neon_yellow

    def get_draw_regions(self):
        """Get regions to display given zone/boundary settings + current render filter."""
        regions = self.get_visible_regions()

        if self.render_mode == 'status':
            if self.render_filter in ('pending', 'approved', 'rejected'):
                regions = [r for r in regions if r.get('status', 'pending') == self.render_filter]
        elif self.render_mode == 'zones':
            if self.render_filter is None:
                regions = [r for r in regions if r.get('zone')]
            else:
                regions = [r for r in regions if r.get('zone') == self.render_filter]
        elif self.render_mode == 'groups':
            if self.render_filter is None:
                regions = [r for r in regions if r.get('group')]
            else:
                regions = [r for r in regions if r.get('group') == self.render_filter]

        return sorted(regions, key=lambda r: (r['center'][1], r['center'][0]))

    def _refresh_render_filter_options(self):
        mode = self.render_mode
        self.render_filter_combo.blockSignals(True)
        self.render_filter_combo.clear()
        if mode == 'status':
            self.render_filter_combo.addItem("All", None)
            self.render_filter_combo.addItem("Pending", 'pending')
            self.render_filter_combo.addItem("Approved", 'approved')
            self.render_filter_combo.addItem("Rejected", 'rejected')
        elif mode == 'zones':
            self.render_filter_combo.addItem("All Zones", None)
            for zid, zinfo in self.zones.items():
                self.render_filter_combo.addItem(zinfo.get('name', str(zid)), zid)
        elif mode == 'groups':
            self.render_filter_combo.addItem("All Groups", None)
            for gname in sorted(self.groups.keys()):
                self.render_filter_combo.addItem(gname, gname)

        # Restore selection if possible
        if self.render_filter is not None:
            idx = self.render_filter_combo.findData(self.render_filter)
            if idx >= 0:
                self.render_filter_combo.setCurrentIndex(idx)
            else:
                self.render_filter = None
        self.render_filter_combo.blockSignals(False)

    def on_render_mode_changed(self):
        self.render_mode = self.render_mode_combo.currentData() or 'status'
        self.render_filter = None
        self._refresh_render_filter_options()
        if self.original_img is None:
            return
        if self.sidebar_panel.isVisible():
            self.show_sidebar()
            self.refresh_image_with_status()
        else:
            self.show_all_regions_labeled()

    def on_render_filter_changed(self):
        self.render_filter = self.render_filter_combo.currentData()
        if self.original_img is None:
            return
        if self.sidebar_panel.isVisible():
            self.show_sidebar()
            self.refresh_image_with_status()
        else:
            self.show_all_regions_labeled()

    def update_sidebar_status(self, region_id, status):
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == region_id:
                widget = self.sidebar.itemWidget(item)
                if widget:
                    name_label = widget.layout().itemAt(0).widget()
                    # Update button styles
                    approve_btn = widget.layout().itemAt(1).widget()
                    reject_btn = widget.layout().itemAt(2).widget()
                    if status == 'approved':
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                        if isinstance(name_label, QLabel):
                            name_label.setStyleSheet("color: white;")
                        approve_btn.setStyleSheet("""
                            QToolButton {
                                background-color: #28a745;
                                color: white;
                                border: none;
                                border-radius: 15px;
                            }
                            QToolButton:hover {
                                background-color: #218838;
                            }
                        """)
                        reject_btn.setStyleSheet("""
                            QToolButton {
                                background-color: #6c757d;
                                color: white;
                                border: none;
                                border-radius: 15px;
                            }
                        """)
                    elif status == 'rejected':
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                        if isinstance(name_label, QLabel):
                            name_label.setStyleSheet("color: #888;")
                        approve_btn.setStyleSheet("""
                            QToolButton {
                                background-color: #6c757d;
                                color: white;
                                border: none;
                                border-radius: 15px;
                            }
                        """)
                        reject_btn.setStyleSheet("""
                            QToolButton {
                                background-color: #dc3545;
                                color: white;
                                border: none;
                                border-radius: 15px;
                            }
                            QToolButton:hover {
                                background-color: #c82333;
                            }
                        """)
                break

    def save_json(self):
        """Save all regions with their status to JSON."""
        if not self.image_path:
            print("⚠️ No image loaded, nothing to save.")
            return
        out_path = self.image_path.rsplit('.', 1)[0] + '_regions.json'
        data = []
        for r in self.regions:
            entry = {
                "id": r['id'],
                "area": int(r['area']),
                "center": list(r['center']),
                "bbox": list(r.get('bbox', (0, 0, 0, 0))),
                "status": r['status']
            }
            data.append(entry)
        with open(out_path, 'w') as f:
            json.dump(data, f, indent=2)
        approved = sum(1 for r in self.regions if r['status'] == 'approved')
        rejected = sum(1 for r in self.regions if r['status'] == 'rejected')
        print(f"💾 Saved {len(data)} regions ({approved} approved, {rejected} rejected) to: {out_path}")
        QMessageBox.information(self, "Saved", f"Saved {len(data)} regions to:\n{out_path}")

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts for faster review."""
        if not self.regions or not self.sidebar.isVisible():
            return super().keyPressEvent(event)

        # Bulk operations when multiple regions are selected
        if self.sidebar_mode == 'regions':
            selected_items = self.sidebar.selectedItems() or []
            if len(selected_items) > 1:
                key = event.key()
                if key in (Qt.Key.Key_R, Qt.Key.Key_Delete):
                    region_ids = []
                    for it in selected_items:
                        rid = it.data(Qt.ItemDataRole.UserRole)
                        if rid:
                            region_ids.append(rid)
                    self._bulk_reject_by_ids(region_ids)
                    return

        key = event.key()
        # Get currently selected region
        current_item = self.sidebar.currentItem()
        if current_item:
            region_id = current_item.data(Qt.ItemDataRole.UserRole)
            idx = self.region_id_map.get(region_id)
            if idx is not None:
                region = self.regions[idx]
                if key == Qt.Key.Key_A or key == Qt.Key.Key_Return:
                    self.approve_region(region)
                    self.select_next_region()
                elif key == Qt.Key.Key_R or key == Qt.Key.Key_Delete:
                    self.reject_region(region)
                    self.select_next_region()
                elif key == Qt.Key.Key_Down or key == Qt.Key.Key_J:
                    self.select_next_region()
                elif key == Qt.Key.Key_Up or key == Qt.Key.Key_K:
                    self.select_prev_region()
                else:
                    super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def _bulk_reject_by_ids(self, region_ids):
        if not region_ids:
            return
        # Deduplicate and keep stable order
        seen = set()
        ordered = []
        for rid in region_ids:
            if rid in seen:
                continue
            seen.add(rid)
            ordered.append(rid)

        changed = False
        for rid in ordered:
            idx = self.region_id_map.get(rid)
            if idx is None:
                continue
            region = self.regions[idx]
            if region.get('status') == 'rejected':
                continue
            region['status'] = 'rejected'
            self.update_sidebar_status(region['id'], 'rejected')
            changed = True

        if changed:
            self.update_status()
            self.schedule_autosave()
            self.refresh_image_with_status()

    def select_next_region(self):
        """Select the next region in the sidebar."""
        row = self.sidebar.currentRow()
        while row < self.sidebar.count() - 1:
            row += 1
            item = self.sidebar.item(row)
            if item.flags() & Qt.ItemFlag.ItemIsSelectable:
                self.sidebar.setCurrentRow(row)
                self.on_sidebar_item_clicked(self.sidebar.currentItem())
                return

    def select_prev_region(self):
        """Select the previous region in the sidebar."""
        row = self.sidebar.currentRow()
        while row > 0:
            row -= 1
            item = self.sidebar.item(row)
            if item.flags() & Qt.ItemFlag.ItemIsSelectable:
                self.sidebar.setCurrentRow(row)
                self.on_sidebar_item_clicked(self.sidebar.currentItem())
                return

    # === Region Editing Methods ===
    
    def get_selected_region(self):
        """Get the currently selected region from sidebar."""
        item = self.sidebar.currentItem()
        if not item:
            return None
        region_id = item.data(Qt.ItemDataRole.UserRole)
        idx = self.region_id_map.get(region_id)
        if idx is not None:
            return self.regions[idx]
        return None
    
    def start_edit_mode(self):
        """Enter edit mode for the selected region's boundary."""
        region = self.get_selected_region()
        if not region:
            QMessageBox.warning(self, "No Selection", "Please select a region first.")
            return
        
        self.edit_mode = True
        self.editing_region = region
        self.edit_points = [tuple(pt[0]) for pt in region['contour']]
        
        # Draw editable points on the image
        self.draw_edit_points()
        self.graphics_view.click_handler = self.handle_edit_click
        
        self.status_label.setText(f"EDIT MODE: {region['id']} - Click to move points, Shift+Click to add, Ctrl+Click to delete")
        print(f"🔧 Edit mode started for {region['id']} ({len(self.edit_points)} points)")
    
    def draw_edit_points(self):
        """Draw the polygon and control points for editing."""
        if not self.editing_region:
            return
        
        base_img = self.processed_img if self.use_processed_img else self.original_img
        overlay = base_img.copy()
        pts = np.array(self.edit_points, dtype=np.int32).reshape(-1, 1, 2)
        
        # Draw filled polygon
        cv2.drawContours(overlay, [pts], -1, (0, 255, 200), thickness=cv2.FILLED)
        overlay = cv2.addWeighted(overlay, 0.3, base_img, 0.7, 0)
        
        # Draw polygon outline
        cv2.polylines(overlay, [pts], True, (0, 255, 0), 2)
        
        # Draw control points
        for i, (x, y) in enumerate(self.edit_points):
            color = (255, 0, 255)  # Magenta
            cv2.circle(overlay, (x, y), 6, color, -1)
            cv2.circle(overlay, (x, y), 6, (255, 255, 255), 1)
        
        h, w = overlay.shape[:2]
        qimg = QImage(overlay.data, w, h, w * 3, QImage.Format.Format_BGR888)
        pixmap = QPixmap.fromImage(qimg)
        self.graphics_view.set_pixmap(pixmap, reset_view=False)
    
    def handle_edit_click(self, x, y):
        """Handle clicks during edit mode."""
        if not self.edit_mode or not self.edit_points:
            return
        
        from PyQt6.QtWidgets import QApplication
        modifiers = QApplication.keyboardModifiers()
        
        # Find nearest point
        min_dist = float('inf')
        nearest_idx = -1
        for i, (px, py) in enumerate(self.edit_points):
            dist = ((px - x) ** 2 + (py - y) ** 2) ** 0.5
            if dist < min_dist:
                min_dist = dist
                nearest_idx = i
        
        if modifiers == Qt.KeyboardModifier.ControlModifier:
            # Ctrl+Click: Delete point (if more than 3 points)
            if len(self.edit_points) > 3 and nearest_idx >= 0 and min_dist < 20:
                del self.edit_points[nearest_idx]
                print(f"Deleted point {nearest_idx}")
        elif modifiers == Qt.KeyboardModifier.ShiftModifier:
            # Shift+Click: Add new point between nearest and next
            if nearest_idx >= 0:
                next_idx = (nearest_idx + 1) % len(self.edit_points)
                # Insert point on the edge
                self.edit_points.insert(next_idx, (x, y))
                print(f"Added point at ({x}, {y})")
        else:
            # Regular click: Move nearest point
            if nearest_idx >= 0 and min_dist < 30:
                self.edit_points[nearest_idx] = (x, y)
                print(f"Moved point {nearest_idx} to ({x}, {y})")
        
        self.draw_edit_points()
    
    def finish_edit_mode(self):
        """Apply the edited boundary to the region."""
        if not self.edit_mode or not self.editing_region:
            return
        
        # Update contour
        new_contour = np.array(self.edit_points, dtype=np.int32).reshape(-1, 1, 2)
        self.editing_region['contour'] = new_contour
        
        # Recalculate area and center
        area = cv2.contourArea(new_contour)
        self.editing_region['area'] = area
        
        M = cv2.moments(new_contour)
        if M['m00'] != 0:
            cx = int(M['m10'] / M['m00'])
            cy = int(M['m01'] / M['m00'])
            self.editing_region['center'] = (cx, cy)
        
        self.editing_region['bbox'] = cv2.boundingRect(new_contour)
        
        # Rebuild region map
        self.rebuild_region_map()
        
        print(f"✅ Applied edits to {self.editing_region['id']}")
        self.cancel_edit_mode()
        self.refresh_image_with_status()
    
    def cancel_edit_mode(self):
        """Cancel edit mode without saving changes."""
        self.edit_mode = False
        self.editing_region = None
        self.editing_zone_id = None
        self.drawing_zone_id = None
        self.edit_points = []
        self.graphics_view.click_handler = self.handle_image_click if self.sidebar_panel.isVisible() else None
        self.update_status()
    
    def rebuild_region_map(self):
        """Rebuild the region_map after editing contours."""
        if self.original_img is None:
            return
        h, w = self.original_img.shape[:2]
        self.region_map = np.zeros((h, w), dtype=np.int32)
        self.region_index_map = {}
        
        for i, region in enumerate(self.regions):
            region_id = i + 1
            cv2.drawContours(self.region_map, [region['contour']], -1, region_id, cv2.FILLED)
            self.region_index_map[region_id] = i

    # === Region Naming / Duplicate / Drag ===

    def show_region_context_menu(self, pos):
        item = self.sidebar.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        rename = menu.addAction("Rename (F2)")
        duplicate = menu.addAction("Duplicate (Ctrl+D)")
        duplicate_opposite = menu.addAction("Duplicate Opposite (Ctrl+Shift+D)")
        assign_zone = menu.addAction("Assign to Zone (Z)")
        action = menu.exec(self.sidebar.mapToGlobal(pos))
        if action == rename:
            self.rename_region()
        elif action == duplicate:
            self.duplicate_region()
        elif action == duplicate_opposite:
            self.duplicate_opposite_region()
        elif action == assign_zone:
            self.assign_region_to_zone()

    def rename_region(self):
        region = self.get_selected_region()
        if not region:
            QMessageBox.warning(self, "No Selection", "Please select a region first.")
            return
        current = region.get('name', region['id'])
        new_name, ok = QInputDialog.getText(self, "Rename Region", "Region name:", text=current)
        if not ok:
            return
        new_name = (new_name or "").strip()
        if not new_name:
            QMessageBox.warning(self, "Invalid Name", "Name cannot be empty.")
            return
        region['name'] = new_name
        self.show_sidebar()
        self.refresh_image_with_status()

    def _generate_region_id_for_zone(self, zone_id):
        if not zone_id:
            return f"region_{len(self.regions) + 1:03d}"
        count = sum(1 for r in self.regions if r.get('zone') == zone_id)
        zlabel = str(zone_id).lower().replace(" ", "")
        if not zlabel.startswith('z'):
            zlabel = f"z{zlabel}"
        return f"{zlabel}-{count + 1}"

    def duplicate_region(self):
        region = self.get_selected_region()
        if not region:
            QMessageBox.warning(self, "No Selection", "Please select a region first.")
            return
        zone_id = region.get('zone')
        new_id = self._generate_region_id_for_zone(zone_id)
        new_region = {
            'id': new_id,
            'name': (region.get('name') or new_id) + " (copy)",
            'contour': region['contour'].copy(),
            'area': float(region['area']),
            'center': tuple(region['center']),
            'bbox': tuple(region.get('bbox', (0, 0, 0, 0))),
            'status': 'pending',
            'zone': zone_id,
        }
        self.regions.append(new_region)
        self.region_id_map = {r['id']: i for i, r in enumerate(self.regions)}
        self.rebuild_region_map()
        self.show_sidebar()
        # Select new one
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == new_id:
                self.sidebar.setCurrentItem(item)
                self.sidebar.scrollToItem(item)
                break
        # Enter drag mode so user can place it
        self.start_drag_mode(new_region)

    def _swap_hand_terms(self, text):
        if not text:
            return text
        # swap using placeholders to avoid double-replace
        t = text
        t = t.replace("R/H", "__RH__").replace("L/H", "__LH__")
        t = t.replace("Right", "__RIGHT__").replace("Left", "__LEFT__")
        t = t.replace("__RH__", "L/H").replace("__LH__", "R/H")
        t = t.replace("__RIGHT__", "Left").replace("__LEFT__", "Right")
        return t

    def _mirror_contour_horizontal(self, contour, image_width):
        # Mirror across vertical axis x = (W-1)/2
        cnt = contour.copy()
        cnt[:, 0, 0] = (image_width - 1) - cnt[:, 0, 0]
        return cnt

    def duplicate_opposite_region(self):
        region = self.get_selected_region()
        if not region:
            QMessageBox.warning(self, "No Selection", "Please select a region first.")
            return
        if self.original_img is None:
            return

        H, W = self.original_img.shape[:2]
        zone_id = region.get('zone')
        new_id = self._generate_region_id_for_zone(zone_id)

        mirrored = self._mirror_contour_horizontal(region['contour'], W)
        area = float(cv2.contourArea(mirrored))
        M = cv2.moments(mirrored)
        if M['m00'] != 0:
            cx = int(M['m10'] / M['m00'])
            cy = int(M['m01'] / M['m00'])
        else:
            x, y, bw, bh = cv2.boundingRect(mirrored)
            cx, cy = x + bw // 2, y + bh // 2

        base_name = region.get('name', region['id'])
        flipped_name = self._swap_hand_terms(base_name)
        if flipped_name == base_name:
            flipped_name = base_name + " (opposite)"

        new_region = {
            'id': new_id,
            'name': flipped_name,
            'contour': mirrored,
            'area': area,
            'center': (cx, cy),
            'bbox': cv2.boundingRect(mirrored),
            'status': 'pending',
            'zone': zone_id,
        }
        self.regions.append(new_region)
        self.region_id_map = {r['id']: i for i, r in enumerate(self.regions)}
        self.rebuild_region_map()
        self.show_sidebar()
        # select new
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == new_id:
                self.sidebar.setCurrentItem(item)
                self.sidebar.scrollToItem(item)
                break
        self.highlight_region(new_region)

    def start_drag_mode(self, region):
        self.drag_mode = True
        self.drag_region = region
        self.status_label.setText("DRAG MODE: Left-click to place duplicated region. Esc to cancel")
        self.graphics_view.click_handler = self.handle_drag_click

    def handle_drag_click(self, x, y):
        if not self.drag_mode or not self.drag_region:
            return
        # Move contour by delta from its current centroid
        cx, cy = self.drag_region['center']
        dx, dy = int(x - cx), int(y - cy)
        cnt = self.drag_region['contour'].copy()
        cnt[:, 0, 0] = cnt[:, 0, 0] + dx
        cnt[:, 0, 1] = cnt[:, 0, 1] + dy
        self.drag_region['contour'] = cnt
        self.drag_region['center'] = (int(x), int(y))
        self.drag_region['bbox'] = cv2.boundingRect(cnt)
        self.drag_region['area'] = float(cv2.contourArea(cnt))
        self.rebuild_region_map()
        self.drag_mode = False
        self.drag_region = None
        self.graphics_view.click_handler = self.handle_image_click if self.sidebar_panel.isVisible() else None
        self.status_label.setText("Placed duplicated region")
        self.refresh_image_with_status()

    # === Zone Management ===

    def create_zone(self):
        zone_name, ok = QInputDialog.getText(self, "Create Zone", "Zone name (e.g. Zone 1):")
        if not ok:
            return
        zone_name = (zone_name or "").strip()
        if not zone_name:
            QMessageBox.warning(self, "Invalid Name", "Zone name cannot be empty")
            return
        zone_id = zone_name
        if zone_id in self.zones:
            QMessageBox.warning(self, "Exists", "A zone with that name already exists")
            return
        color = self.zone_colors[len(self.zones) % len(self.zone_colors)]
        self.zones[zone_id] = {'name': zone_name, 'color': color, 'visible': True}
        self.refresh_zone_ui()

    def refresh_zone_ui(self):
        # Combo
        if hasattr(self, 'zone_filter_combo'):
            current = self.zone_filter_combo.currentData()
            self.zone_filter_combo.blockSignals(True)
            self.zone_filter_combo.clear()
            self.zone_filter_combo.addItem("All Zones", None)
            for zid, zinfo in self.zones.items():
                self.zone_filter_combo.addItem(zinfo['name'], zid)
            # restore
            if current is not None:
                idx = self.zone_filter_combo.findData(current)
                if idx >= 0:
                    self.zone_filter_combo.setCurrentIndex(idx)
            self.zone_filter_combo.blockSignals(False)

        # Menu entries
        if hasattr(self, 'zone_filter_menu'):
            self.zone_filter_menu.clear()
            show_all_action = self.zone_filter_menu.addAction("Show All Zones")
            show_all_action.triggered.connect(lambda: self.set_zone_filter(None))
            self.zone_filter_menu.addSeparator()
            for zid, zinfo in self.zones.items():
                act = self.zone_filter_menu.addAction(f"Show only {zinfo['name']}")
                act.triggered.connect(lambda checked=False, z=zid: self.set_zone_filter(z))

        if hasattr(self, 'render_filter_combo'):
            self._refresh_render_filter_options()

    def on_zone_filter_changed(self):
        zid = self.zone_filter_combo.currentData()
        self.set_zone_filter(zid)

    def set_zone_filter(self, zone_id):
        self.active_zone_filter = zone_id
        if self.original_img is None:
            return
        if self.sidebar_panel.isVisible():
            self.show_sidebar()
        else:
            self.show_all_regions_labeled()

    def on_boundary_view_toggled(self, state):
        self.boundary_view = state == Qt.CheckState.Checked
        if self.original_img is None:
            return
        if self.sidebar_panel.isVisible():
            self.show_sidebar()
        else:
            self.show_all_regions_labeled()

    def on_show_boundaries_toggled(self, state):
        self.show_zone_boundaries = state == Qt.CheckState.Checked
        if self.original_img is None:
            return
        if self.sidebar_panel.isVisible():
            self.refresh_image_with_status()
        else:
            self.show_all_regions_labeled()

    def _regions_in_zone_boundary(self, zone_id):
        zinfo = self.zones.get(zone_id)
        if not zinfo:
            return []
        contour = zinfo.get('contour')
        if contour is None:
            return []
        result = []
        for r in self.regions:
            cx, cy = r['center']
            inside = cv2.pointPolygonTest(contour, (float(cx), float(cy)), False)
            if inside >= 0:
                result.append(r)
        return result

    def get_visible_regions(self):
        # Boundary view: show regions whose centroids fall within the selected zone boundary
        if self.boundary_view and self.active_zone_filter is not None:
            return self._regions_in_zone_boundary(self.active_zone_filter)

        # Otherwise: normal filtering by explicit region->zone assignment
        if self.active_zone_filter is None:
            return list(self.regions)
        return [r for r in self.regions if r.get('zone') == self.active_zone_filter]

    def assign_region_to_zone(self):
        region = self.get_selected_region()
        if not region:
            QMessageBox.warning(self, "No Selection", "Please select a region first.")
            return
        if not self.zones:
            QMessageBox.warning(self, "No Zones", "Create a zone first (Zones > Create New Zone)")
            return
        items = [z['name'] for z in self.zones.values()]
        zid_by_name = {z['name']: zid for zid, z in self.zones.items()}
        choice, ok = QInputDialog.getItem(self, "Assign Zone", "Zone:", items, 0, False)
        if not ok:
            return
        zid = zid_by_name.get(choice)
        region['zone'] = zid
        # Optionally re-id to zone numbering if it isn't already in z?-?
        if isinstance(region.get('id'), str) and not region['id'].lower().startswith('z'):
            region['id'] = self._generate_region_id_for_zone(zid)
        if 'name' not in region:
            region['name'] = region['id']
        self.region_id_map = {r['id']: i for i, r in enumerate(self.regions)}
        self.rebuild_region_map()
        self.show_sidebar()
        self.refresh_image_with_status()

    def edit_zone_boundary(self):
        if not self.zones:
            QMessageBox.warning(self, "No Zones", "Create a zone first (Zones > Create New Zone)")
            return

        zone_names = [zinfo['name'] for zinfo in self.zones.values()]
        zid_by_name = {zinfo['name']: zid for zid, zinfo in self.zones.items()}
        choice, ok = QInputDialog.getItem(self, "Edit Zone Boundary", "Zone:", zone_names, 0, False)
        if not ok:
            return

        zid = zid_by_name.get(choice)
        if zid is None:
            return

        zinfo = self.zones[zid]
        if zinfo.get('contour') is None:
            self.start_draw_zone(zid)
        else:
            self.start_edit_zone(zid)

    def start_draw_zone(self, zone_id):
        self.edit_mode = True
        self.editing_region = None
        self.editing_zone_id = None
        self.drawing_zone_id = zone_id
        self.edit_points = []
        self.graphics_view.click_handler = self.handle_draw_zone_click
        self.status_label.setText(
            f"DRAW ZONE: {self.zones[zone_id]['name']} | Click to add points, Enter to finish, Esc to cancel"
        )

    def handle_draw_zone_click(self, x, y):
        if not self.edit_mode or self.drawing_zone_id is None:
            return
        self.edit_points.append((x, y))
        self.draw_zone_preview()

    def draw_zone_preview(self):
        base_img = self.processed_img if self.use_processed_img else self.original_img
        overlay = base_img.copy()

        zone_color = (255, 255, 255)
        if self.drawing_zone_id in self.zones:
            zone_color = self.zones[self.drawing_zone_id]['color']

        if len(self.edit_points) >= 2:
            pts = np.array(self.edit_points, dtype=np.int32)
            cv2.polylines(overlay, [pts], False, zone_color, 2)
        for x, y in self.edit_points:
            cv2.circle(overlay, (x, y), 5, (255, 0, 255), -1)

        h, w = overlay.shape[:2]
        qimg = QImage(overlay.data, w, h, w * 3, QImage.Format.Format_BGR888)
        pixmap = QPixmap.fromImage(qimg)
        self.graphics_view.set_pixmap(pixmap, reset_view=False)

    def start_edit_zone(self, zone_id):
        zinfo = self.zones.get(zone_id)
        if not zinfo or zinfo.get('contour') is None:
            QMessageBox.warning(self, "No Boundary", "This zone has no boundary yet.")
            return
        self.edit_mode = True
        self.editing_region = None
        self.drawing_zone_id = None
        self.editing_zone_id = zone_id
        self.edit_points = [tuple(pt[0]) for pt in zinfo['contour']]
        self.graphics_view.click_handler = self.handle_zone_edit_click
        self.status_label.setText(
            f"EDIT ZONE: {zinfo['name']} | Click move, Shift+Click add, Ctrl+Click delete"
        )
        self.draw_zone_edit_points()

    def handle_zone_edit_click(self, x, y):
        if not self.edit_mode or self.editing_zone_id is None or not self.edit_points:
            return

        from PyQt6.QtWidgets import QApplication
        modifiers = QApplication.keyboardModifiers()

        min_dist = float('inf')
        nearest_idx = -1
        for i, (px, py) in enumerate(self.edit_points):
            dist = ((px - x) ** 2 + (py - y) ** 2) ** 0.5
            if dist < min_dist:
                min_dist = dist
                nearest_idx = i

        if modifiers == Qt.KeyboardModifier.ControlModifier:
            if len(self.edit_points) > 3 and nearest_idx >= 0 and min_dist < 20:
                del self.edit_points[nearest_idx]
        elif modifiers == Qt.KeyboardModifier.ShiftModifier:
            if nearest_idx >= 0:
                next_idx = (nearest_idx + 1) % len(self.edit_points)
                self.edit_points.insert(next_idx, (x, y))
        else:
            if nearest_idx >= 0 and min_dist < 30:
                self.edit_points[nearest_idx] = (x, y)

        self.draw_zone_edit_points()

    def draw_zone_edit_points(self):
        if self.editing_zone_id is None:
            return

        base_img = self.processed_img if self.use_processed_img else self.original_img
        overlay = base_img.copy()

        zinfo = self.zones.get(self.editing_zone_id)
        zone_color = zinfo['color'] if zinfo else (255, 255, 255)

        pts = np.array(self.edit_points, dtype=np.int32).reshape(-1, 1, 2)
        cv2.drawContours(overlay, [pts], -1, zone_color, thickness=cv2.FILLED)
        overlay = cv2.addWeighted(overlay, 0.15, base_img, 0.85, 0)
        cv2.polylines(overlay, [pts], True, zone_color, 2)

        for x, y in self.edit_points:
            cv2.circle(overlay, (x, y), 6, (255, 0, 255), -1)
            cv2.circle(overlay, (x, y), 6, (255, 255, 255), 1)

        h, w = overlay.shape[:2]
        qimg = QImage(overlay.data, w, h, w * 3, QImage.Format.Format_BGR888)
        pixmap = QPixmap.fromImage(qimg)
        self.graphics_view.set_pixmap(pixmap, reset_view=False)

    def finish_zone_edit_or_draw(self):
        if len(self.edit_points) < 3:
            QMessageBox.warning(self, "Not Enough Points", "Need at least 3 points for a zone boundary")
            return

        contour = np.array(self.edit_points, dtype=np.int32).reshape(-1, 1, 2)
        zid = self.editing_zone_id if self.editing_zone_id is not None else self.drawing_zone_id
        if zid is None:
            return

        self.zones[zid]['contour'] = contour
        self.refresh_zone_ui()
        self.cancel_edit_mode()

        if self.sidebar_panel.isVisible():
            self.refresh_image_with_status()
        else:
            self.show_all_regions_labeled()

    # === Image Processing: Color removal / Blueprint mode ===

    def remove_colors_from_image(self):
        if self.original_img is None:
            QMessageBox.warning(self, "No Image", "Please load an image first")
            return
        # Create a blueprint-like B/W image (edges in dark blue)
        img = self.original_img
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Strong denoise
        gray_blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(gray_blur, 40, 140)
        edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)), iterations=1)
        # Background white
        bw = np.full_like(img, 255)
        # Draw edges in blue-ish (BGR)
        bw[edges > 0] = (180, 60, 0)
        self.processed_img = bw
        self.use_processed_img = True
        if hasattr(self, 'toggle_bw_action'):
            self.toggle_bw_action.setChecked(True)
        self.show_all_regions_labeled()

    def toggle_bw_mode(self):
        if self.original_img is None:
            return
        self.use_processed_img = not self.use_processed_img
        if self.use_processed_img and self.processed_img is None:
            self.remove_colors_from_image()
            return
        if self.sidebar_panel.isVisible():
            self.refresh_image_with_status()
        else:
            self.show_all_regions_labeled()

    # === Database Mapping (SQLite) ===

    def _connect_default_database(self):
        """Connect to the shared DB in the common folder (creates if missing)."""
        try:
            default_path = str(self.common_dir / "blueprint_mapper.sqlite")
            self.db_path = default_path
            self.db_conn = sqlite3.connect(self.db_path)
            self.db_conn.row_factory = sqlite3.Row
            self._init_db_schema()
        except Exception as e:
            self.db_path = None
            self.db_conn = None
            print(f"⚠️ Failed to connect default DB: {e}")

    def connect_database(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Create/Open SQLite DB", "", "SQLite DB (*.db *.sqlite)")
        if not file_path:
            return
        self.db_path = file_path
        self.db_conn = sqlite3.connect(self.db_path)
        self.db_conn.row_factory = sqlite3.Row
        self._init_db_schema()
        QMessageBox.information(self, "Database", f"Connected to:\n{self.db_path}")

    def _init_db_schema(self):
        if not self.db_conn:
            return
        cur = self.db_conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS regions (
                region_id TEXT PRIMARY KEY,
                dash TEXT,
                name TEXT,
                zone INTEGER,
                op_card TEXT,
                drawing TEXT,
                sheet INTEGER,
                material TEXT,
                material_type TEXT,
                qty REAL,
                unit TEXT,
                detail_page TEXT,
                partner_locator_uid TEXT,
                partner_bin TEXT,
                qty_on_hand REAL,
                min_qty REAL,
                low_stock_alert_qty REAL,
                updated_at TEXT
            )
        """)

        # Library: images, views, and per-view region maps
        cur.execute("""
            CREATE TABLE IF NOT EXISTS images (
                image_id TEXT PRIMARY KEY,
                original_name TEXT,
                stored_path TEXT,
                added_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS views (
                view_id TEXT PRIMARY KEY,
                image_id TEXT,
                name TEXT,
                x INTEGER,
                y INTEGER,
                w INTEGER,
                h INTEGER,
                created_at TEXT,
                FOREIGN KEY(image_id) REFERENCES images(image_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS view_regions (
                view_id TEXT,
                region_id TEXT,
                name TEXT,
                status TEXT,
                zone TEXT,
                group_name TEXT,
                contour_json TEXT,
                bbox_json TEXT,
                center_x INTEGER,
                center_y INTEGER,
                updated_at TEXT,
                PRIMARY KEY(view_id, region_id),
                FOREIGN KEY(view_id) REFERENCES views(view_id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS view_maps (
                view_id TEXT PRIMARY KEY,
                map_json TEXT,
                updated_at TEXT,
                FOREIGN KEY(view_id) REFERENCES views(view_id)
            )
        """)
        self.db_conn.commit()

    def add_image_to_library(self):
        """Add an image to the shared library and create one or more named views."""
        if not self.db_conn:
            self._connect_default_database()
        if not self.db_conn:
            QMessageBox.warning(self, "Library", "Database is not available.")
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Add Image to Library",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not file_path:
            return

        try:
            image_id = uuid.uuid4().hex
            src = Path(file_path)
            safe_name = f"{image_id}_{src.name}"
            dst = self.common_dir / "images" / safe_name
            shutil.copy2(str(src), str(dst))

            cur = self.db_conn.cursor()
            cur.execute(
                "INSERT INTO images (image_id, original_name, stored_path, added_at) VALUES (?,?,?,?)",
                (image_id, src.name, str(dst), datetime.utcnow().isoformat()),
            )

            view_names_text, ok = QInputDialog.getText(
                self,
                "Views",
                "View names (comma-separated):",
                text="Full"
            )
            if not ok:
                self.db_conn.commit()
                return

            view_names = [v.strip() for v in (view_names_text or "").split(",") if v.strip()]
            if not view_names:
                view_names = ["Full"]

            for name in view_names:
                view_id = uuid.uuid4().hex
                # Optional crop rectangle for the view
                rect_text, ok_rect = QInputDialog.getText(
                    self,
                    f"View Rect: {name}",
                    "Crop rect x,y,w,h (blank = full image):",
                    text=""
                )
                x = y = w = h = None
                if ok_rect and (rect_text or "").strip():
                    try:
                        parts = [int(p.strip()) for p in rect_text.split(",")]
                        if len(parts) == 4:
                            x, y, w, h = parts
                    except Exception:
                        x = y = w = h = None

                cur.execute(
                    """
                    INSERT INTO views (view_id, image_id, name, x, y, w, h, created_at)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (view_id, image_id, name, x, y, w, h, datetime.utcnow().isoformat()),
                )

            self.db_conn.commit()
            QMessageBox.information(self, "Library", "Image added to library.")
        except Exception as e:
            QMessageBox.critical(self, "Library", f"Failed to add image:\n{e}")

    def open_library_view(self):
        """Pick a library image + view and load its map."""
        if not self.db_conn:
            self._connect_default_database()
        if not self.db_conn:
            QMessageBox.warning(self, "Library", "Database is not available.")
            return

        cur = self.db_conn.cursor()
        images = cur.execute("SELECT image_id, original_name FROM images ORDER BY added_at DESC").fetchall()
        if not images:
            QMessageBox.information(self, "Library", "No images in library yet. Use Library → Add Image to Library…")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Open Library View")
        layout = QFormLayout(dlg)
        img_combo = QComboBox()
        view_combo = QComboBox()
        layout.addRow("Image:", img_combo)
        layout.addRow("View:", view_combo)

        for row in images:
            img_combo.addItem(row["original_name"], row["image_id"])

        def refresh_views():
            view_combo.clear()
            image_id = img_combo.currentData()
            rows = cur.execute(
                "SELECT view_id, name FROM views WHERE image_id=? ORDER BY created_at ASC",
                (image_id,),
            ).fetchall()
            for r in rows:
                view_combo.addItem(r["name"], r["view_id"])

        img_combo.currentIndexChanged.connect(refresh_views)
        refresh_views()

        btn_row = QHBoxLayout()
        open_btn = QPushButton("Open")
        cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(open_btn)
        btn_row.addWidget(cancel_btn)
        layout.addRow(btn_row)

        def do_open():
            view_id = view_combo.currentData()
            if view_id:
                dlg.accept()
                self._open_library_view_by_id(view_id)

        open_btn.clicked.connect(do_open)
        cancel_btn.clicked.connect(dlg.reject)

        dlg.exec()

    def _open_library_view_by_id(self, view_id):
        if not self.db_conn:
            return
        cur = self.db_conn.cursor()
        row = cur.execute(
            """
            SELECT v.view_id, v.image_id, v.name, v.x, v.y, v.w, v.h, i.stored_path
            FROM views v
            JOIN images i ON i.image_id = v.image_id
            WHERE v.view_id=?
            """,
            (view_id,),
        ).fetchone()
        if not row:
            QMessageBox.warning(self, "Library", "View not found.")
            return

        stored_path = row["stored_path"]
        rect = None
        if row["x"] is not None and row["y"] is not None and row["w"] is not None and row["h"] is not None:
            rect = (int(row["x"]), int(row["y"]), int(row["w"]), int(row["h"]))

        img_full = cv2.imread(stored_path)
        if img_full is None:
            QMessageBox.warning(self, "Library", f"Failed to read image:\n{stored_path}")
            return

        self.library_image_id = row["image_id"]
        self.library_view_id = row["view_id"]
        self.library_view_rect = rect

        if rect and rect[2] > 0 and rect[3] > 0:
            x, y, w, h = rect
            img = img_full[max(0, y):max(0, y) + h, max(0, x):max(0, x) + w].copy()
        else:
            img = img_full

        self.original_img = img
        self.processed_img = None
        self.use_processed_img = False
        self.image_path = stored_path

        loaded = self._load_view_map_from_db(self.library_view_id)
        if not loaded:
            # No saved map yet: detect fresh regions for this view
            self.detect_regions()
            self.schedule_autosave()

        # Bring up control view by default
        self.show_sidebar()
        self.refresh_image_with_status()

    def view_database(self):
        if not self.db_conn:
            QMessageBox.warning(self, "No DB", "Connect a database first")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Region Database")
        dlg.resize(1200, 600)
        layout = QVBoxLayout(dlg)
        table = QTableWidget()
        layout.addWidget(table)
        cur = self.db_conn.cursor()
        rows = cur.execute("SELECT * FROM regions ORDER BY region_id").fetchall()
        cols = [d[0] for d in cur.description] if rows else [
            'region_id','dash','name','zone','op_card','drawing','sheet','material','material_type','qty','unit',
            'detail_page','partner_locator_uid','partner_bin','qty_on_hand','min_qty','low_stock_alert_qty','updated_at'
        ]
        table.setColumnCount(len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.setRowCount(len(rows))
        for r_i, row in enumerate(rows):
            for c_i, col in enumerate(cols):
                val = row[col] if col in row.keys() else ""
                table.setItem(r_i, c_i, QTableWidgetItem("" if val is None else str(val)))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        dlg.exec()

    def export_to_csv(self):
        if not self.db_conn:
            QMessageBox.warning(self, "No DB", "Connect a database first")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV (*.csv)")
        if not file_path:
            return
        cur = self.db_conn.cursor()
        rows = cur.execute("SELECT * FROM regions ORDER BY region_id").fetchall()
        cols = [d[0] for d in cur.description]
        import csv
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(cols)
            for row in rows:
                w.writerow([row[c] for c in cols])
        QMessageBox.information(self, "Export", f"Exported {len(rows)} rows to:\n{file_path}")

    def import_from_csv(self):
        if not self.db_conn:
            QMessageBox.warning(self, "No DB", "Connect a database first")
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "Import CSV", "", "CSV (*.csv)")
        if not file_path:
            return
        import csv
        with open(file_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        cur = self.db_conn.cursor()
        for r in rows:
            rid = (r.get('Region ID') or r.get('region_id') or '').strip()
            if not rid:
                continue
            # Normalize headers from your Excel screenshot
            def g(*keys):
                for k in keys:
                    if k in r and r[k] != '':
                        return r[k]
                return None
            zone_val = g('Zone', 'zone')
            try:
                zone_int = int(zone_val) if zone_val is not None and str(zone_val).strip() != '' else None
            except:
                zone_int = None
            cur.execute("""
                INSERT INTO regions (
                    region_id, dash, name, zone, op_card, drawing, sheet, material, material_type, qty, unit,
                    detail_page, partner_locator_uid, partner_bin, qty_on_hand, min_qty, low_stock_alert_qty, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(region_id) DO UPDATE SET
                    dash=excluded.dash,
                    name=excluded.name,
                    zone=excluded.zone,
                    op_card=excluded.op_card,
                    drawing=excluded.drawing,
                    sheet=excluded.sheet,
                    material=excluded.material,
                    material_type=excluded.material_type,
                    qty=excluded.qty,
                    unit=excluded.unit,
                    detail_page=excluded.detail_page,
                    partner_locator_uid=excluded.partner_locator_uid,
                    partner_bin=excluded.partner_bin,
                    qty_on_hand=excluded.qty_on_hand,
                    min_qty=excluded.min_qty,
                    low_stock_alert_qty=excluded.low_stock_alert_qty,
                    updated_at=excluded.updated_at
            """, (
                rid,
                g('Dash','dash'),
                g('Name','name'),
                zone_int,
                g('OP Card','op_card'),
                g('Drawing','drawing'),
                g('Sheet','sheet'),
                g('Material','material'),
                g('Material Type','material_type'),
                g('QTY','qty'),
                g('Unit','unit'),
                g('Detail Page','detail_page'),
                g('Partner Locator UID','partner_locator_uid'),
                g('Partner Bin','partner_bin'),
                g('QTY on Hand','qty_on_hand'),
                g('Min. QTY','min_qty'),
                g('Low Stock Alert QTY','low_stock_alert_qty'),
                datetime.utcnow().isoformat()
            ))
        self.db_conn.commit()
        QMessageBox.information(self, "Import", f"Imported/updated {len(rows)} rows")
    
    def start_draw_new_region(self):
        """Start drawing a new region polygon."""
        self.edit_mode = True
        self.editing_region = None
        self.edit_points = []
        self.graphics_view.click_handler = self.handle_draw_new_click
        self.status_label.setText("DRAW MODE: Click to add points, Enter to finish, Esc to cancel")
        print("✏️ Draw new region mode - click to add polygon points")
    
    def handle_draw_new_click(self, x, y):
        """Handle clicks when drawing a new region."""
        self.edit_points.append((x, y))
        self.draw_new_region_preview()
    
    def draw_new_region_preview(self):
        """Draw preview of the new region being created."""
        base_img = self.processed_img if self.use_processed_img else self.original_img
        overlay = base_img.copy()
        
        if len(self.edit_points) >= 2:
            pts = np.array(self.edit_points, dtype=np.int32)
            cv2.polylines(overlay, [pts], False, (0, 255, 0), 2)
        
        for x, y in self.edit_points:
            cv2.circle(overlay, (x, y), 5, (255, 0, 255), -1)
        
        h, w = overlay.shape[:2]
        qimg = QImage(overlay.data, w, h, w * 3, QImage.Format.Format_BGR888)
        pixmap = QPixmap.fromImage(qimg)
        self.graphics_view.set_pixmap(pixmap, reset_view=False)
    
    def delete_selected_region(self):
        """Delete the currently selected region."""
        region = self.get_selected_region()
        if not region:
            QMessageBox.warning(self, "No Selection", "Please select a region first.")
            return
        
        reply = QMessageBox.question(self, "Delete Region", 
                                      f"Delete {region['id']}?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            idx = self.region_id_map[region['id']]
            del self.regions[idx]
            # Rebuild maps
            self.region_id_map = {r['id']: i for i, r in enumerate(self.regions)}
            self.rebuild_region_map()
            self.show_sidebar()
            print(f"🗑️ Deleted {region['id']}")
    
    def keyPressEvent(self, event):
        """Handle keyboard shortcuts."""
        key = event.key()

        # Cancel drag mode
        if self.drag_mode and key == Qt.Key.Key_Escape:
            self.drag_mode = False
            self.drag_region = None
            self.graphics_view.click_handler = self.handle_image_click if self.sidebar_panel.isVisible() else None
            self.status_label.setText("Drag cancelled")
            return
        
        # Edit mode shortcuts
        if self.edit_mode:
            if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                if self.editing_region:
                    self.finish_edit_mode()
                elif self.editing_zone_id is not None or self.drawing_zone_id is not None:
                    self.finish_zone_edit_or_draw()
                elif len(self.edit_points) >= 3:
                    # Finish drawing new region
                    self.create_region_from_points()
                return
            elif key == Qt.Key.Key_Escape:
                self.cancel_edit_mode()
                return
        
        # Normal mode shortcuts
        if not self.regions or not self.sidebar.isVisible():
            return super().keyPressEvent(event)

        current_item = self.sidebar.currentItem()
        if current_item:
            region_id = current_item.data(Qt.ItemDataRole.UserRole)
            idx = self.region_id_map.get(region_id)
            if idx is not None:
                region = self.regions[idx]
                if key == Qt.Key.Key_A:
                    self.approve_region(region)
                    self.select_next_region()
                elif key == Qt.Key.Key_R:
                    self.reject_region(region)
                    self.select_next_region()
                elif key == Qt.Key.Key_Down or key == Qt.Key.Key_J:
                    self.select_next_region()
                elif key == Qt.Key.Key_Up or key == Qt.Key.Key_K:
                    self.select_prev_region()
                else:
                    super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)
    
    def create_region_from_points(self):
        """Create a new region from the drawn points."""
        if len(self.edit_points) < 3:
            QMessageBox.warning(self, "Not Enough Points", "Need at least 3 points to create a region.")
            return
        
        # Ask for region name
        name, ok = QInputDialog.getText(self, "Region Name", "Enter region ID (or leave blank for auto):")
        
        contour = np.array(self.edit_points, dtype=np.int32).reshape(-1, 1, 2)
        area = cv2.contourArea(contour)
        
        M = cv2.moments(contour)
        if M['m00'] != 0:
            cx = int(M['m10'] / M['m00'])
            cy = int(M['m01'] / M['m00'])
        else:
            x, y, bw, bh = cv2.boundingRect(contour)
            cx, cy = x + bw // 2, y + bh // 2
        
        region_id = name if (ok and name) else f"region_{len(self.regions) + 1:03d}"
        
        region_data = {
            'id': region_id,
            'contour': contour,
            'area': area,
            'center': (cx, cy),
            'bbox': cv2.boundingRect(contour),
            'status': 'pending'
        }
        self.regions.append(region_data)
        self.region_id_map[region_id] = len(self.regions) - 1
        self.rebuild_region_map()
        
        print(f"✅ Created new region: {region_id}")
        self.cancel_edit_mode()
        self.show_sidebar()


if __name__ == "__main__":
    print("🚀 Starting Blueprint Mapper (Curation Mode with Zoom/Pan)...")
    app = QApplication(sys.argv)
    window = BlueprintMapper()
    window.show()
    print("🟢 Main window displayed. Go to File > Open Image.")
    sys.exit(app.exec())