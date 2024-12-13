import argparse
from pathlib import Path
# import sys
import os
from qtpy import QtWidgets
from qtpy import QtGui, QtCore
import logging
import webbrowser
# from qtpy.QtCore import Signal

from packaging import version as version_mod

from pymodaq_utils.logger import set_logger, get_module_name
from pymodaq_utils.utils import get_version
# from pymodaq_gui.h5modules.browsing import H5Browser
from pymodaq_gui.utils import CustomApp, DockArea, Dock
from pymodaq_gui.h5modules.browsing import View
from pymodaq_gui.plotting.data_viewers.viewerND import ViewerND
from pymodaq_gui.utils.file_io import select_file, select_file_filter
from pymodaq_gui.messenger import messagebox
from pymodaq_gui.utils.utils import pngbinary2Qlabel, h5tree_to_QTree
from pymodaq_gui.parameter import ioxml
from pymodaq_gui.managers.parameter_manager import ParameterManager
from pymodaq_data.h5modules.exporter import ExporterFactory
from pymodaq_data.h5modules.browsing import H5BrowserUtil
from pymodaq_data.h5modules import data_saving
# from pymodaq_gui import utils as gutils
# from pymodaq_utils.config import Config

# from pymodaq_h5browser.utils import Config as PluginConfig

os.environ["HDF5_USE_FILE_LOCKING"] = "FALSE"

logger = set_logger(get_module_name(__file__))

# main_config = Config()
# plugin_config = PluginConfig()


class H5Browser(CustomApp):
    """UI used to explore h5 files, plot and export subdatas

    Parameters
    ----------
    parent: QtWidgets container
        either a QWidget or a QMainWindow
    h5file: h5file instance
        exact type depends on the backend
    h5file_path: str or Path
        if specified load the corresponding file, otherwise open a select file dialog
    backend: str
        either 'tables, 'h5py' or 'h5pyd'

    See Also
    --------
    H5Backend, H5Backend
    """
    data_node_signal = QtCore.Signal(str)  # the path of a node where data should be monitored, displayed...
    # whatever use from the caller
    status_signal = QtCore.Signal(str)

    def __init__(self, parent: QtWidgets.QMainWindow, h5file=None, h5file_path=None, backend='tables'):
        super(H5Browser, self).__init__(parent)
        # QObject.__init__(self)
        # toolbar = QtWidgets.QToolBar()
        # ActionManager.__init__(self)  # , toolbar=toolbar)

        if not isinstance(parent, QtWidgets.QMainWindow):
            raise Exception('no valid parent container, expected a QMainWindow')
        #
        self.main_window = parent
        self.parent_widget = QtWidgets.QWidget()
        self.main_window.setCentralWidget(self.parent_widget)
        self.main_window.addToolBar(self.toolbar)
        self.statusbar = self.main_window.statusBar()
        self._menubar = self.main_window.menuBar()
        self.current_node_path = None

        self.settings_attributes = ParameterManager()
        # self.settings = ParameterManager()

        # construct the UI interface
        self.view = View(self.parent_widget, settings_tree=self.settings_tree,
                         settings_attributes_tree=self.settings_attributes.settings_tree)
        self.view.item_clicked_sig.connect(self.show_h5_attributes)
        self.view.item_double_clicked_sig.connect(self.show_h5_data)
        self.hyper_viewer = ViewerND(self.view.viewer_widget)

        # self.setup_actions()
        # self.setup_menu()
        # self.connect_things()
        self.setup_ui()

        # construct the h5 interface and load the file (or open a select file message)
        self.h5utils = H5BrowserUtil(backend=backend)
        self.data_loader = None
        self.load_file(h5file, h5file_path)

    def setup_docks(self):
        """Mandatory method to be subclassed to setup the docks layout
        """
        pass

    def connect_things(self):
        self.connect_action('export', self.export_data)
        self.connect_action('comment', self.add_comments)
        self.connect_action('load', lambda: self.load_file(None, None))
        self.connect_action('save', self.save_file)
        self.connect_action('quit', self.quit_fun)
        self.connect_action('about', self.show_about)
        self.connect_action('help', self.show_help)
        self.connect_action('log', self.show_log)

        self.connect_action('plot_node', lambda: self.get_node_and_plot(False))
        self.connect_action('plot_nodes', lambda: self.get_node_and_plot(False, True))
        self.connect_action('plot_node_with_bkg', lambda: self.get_node_and_plot(True))
        self.connect_action('plot_nodes_with_bkg', lambda: self.get_node_and_plot(True, True))

        self.status_signal.connect(self.add_log)

    def get_node_and_plot(self, with_bkg, plot_all=False):
        self.show_h5_data(item=None, with_bkg=with_bkg, plot_all=plot_all)

    def load_file(self, h5file=None, h5file_path=None):
        if h5file is None:
            if h5file_path is None:
                h5file_path = select_file(save=False, ext=['h5', 'hdf5'])
            if Path(h5file_path).is_file():
                if self.h5utils.isopen():
                    self.h5utils.close_file()

                self.h5utils.open_file(h5file_path, 'r+')
            else:
                return
        else:
            self.h5utils.h5file = h5file

        self.data_loader = data_saving.DataLoader(self.h5utils)
        self.check_version()
        self.populate_tree()
        self.view.h5file_tree.expand_all()

    def setup_menu(self, menubar: QtWidgets.QMenuBar = None):
        # menubar = self.main_window.menuBar()
        file_menu = menubar.addMenu('File')
        self.affect_to('load', file_menu)
        self.affect_to('save', file_menu)
        file_menu.addSeparator()
        self.affect_to('quit', file_menu)

        help_menu = menubar.addMenu('?')
        self.affect_to('about', help_menu)
        self.affect_to('help', help_menu)
        self.affect_to('log', help_menu)

    def setup_actions(self):
        self.add_action('export', 'Export as', 'SaveAs', tip='Export node content (and children) as ',
                        toolbar=self.toolbar)
        self.add_action('comment', 'Add Comment', 'properties', tip='Add comments to the node',
                        toolbar=self.toolbar)
        self.add_action('plot_node', 'Plot Node', 'color', tip='Plot the current node',
                        toolbar=self.toolbar)
        self.add_action('plot_nodes', 'Plot Nodes', 'color', tip='Plot all nodes hanging from the same parent',
                        toolbar=self.toolbar)
        self.add_action('plot_node_with_bkg', 'Plot Node With Bkg', 'color', tip='Plot the current node with background'
                                                                                 ' substraction if possible',
                        toolbar=self.toolbar)
        self.add_action('plot_nodes_with_bkg', 'Plot Nodes With Bkg', 'color', tip='Plot all nodes hanging from'
                                                                                   ' the same parent with background'
                                                                                   ' substraction if possible',
                        toolbar=self.toolbar)
        self.view.add_actions([self.get_action('export'), self.get_action('comment'),
                               self.get_action('plot_node'), self.get_action('plot_nodes'),
                               self.get_action('plot_node_with_bkg'),
                               self.get_action('plot_nodes_with_bkg')])

        self.add_action('load', 'Load File', 'Open', tip='Open a new file')
        self.add_action('save', 'Save File as', 'SaveAs', tip='Save as another file')
        self.add_action('quit', 'Quit the application', 'Exit', tip='Quit the application')
        self.add_action('about', 'About', tip='About')
        self.add_action('help', 'Help', 'Help', tip='Show documentation',
                        shortcut=QtCore.Qt.Key_F1)
        self.add_action('log', 'Show Log', 'information2', tip='Open Log')

    def check_version(self):
        """Check version of PyMoDAQ to assert if file is compatible or not with the current version of the Browser"""
        if 'pymodaq_version' in self.h5utils.root().attrs.attrs_name:
            if version_mod.parse(self.h5utils.root().attrs['pymodaq_version']) < version_mod.parse('4.0.0a0'):
                msg_box = messagebox(severity='warning', title='Invalid version',
                                     text=f"Your file has been saved using PyMoDAQ "
                                          f"version {self.h5utils.root().attrs['pymodaq_version']} "
                                     )
                self.quit_fun()

    def add_comments(self, status: bool, comment=''):
        """Add comments to a node

        Parameters
        ----------
        status: bool
        comment: str
            The comment to be added in a comment attribute to the current node path

        See Also
        --------
        current_node_path
        """
        try:
            self.current_node_path = self.get_tree_node_path()
            node = self.h5utils.get_node(self.current_node_path)
            if 'comments' in node.attrs.attrs_name:
                tmp = node.attrs['comments']
            else:
                tmp = ''
            if comment == '':
                text, res = QtWidgets.QInputDialog.getMultiLineText('Enter comments', 'Enter comments here:', tmp)
                if res and text != '':
                    comment = text
                node.attrs['comments'] = comment
            else:
                node.attrs['comments'] = tmp + comment

            self.h5utils.flush()

        except Exception as e:
            logger.exception(str(e))

    def get_tree_node_path(self):
        """Get the node path of the currently selected node in the UI"""
        return self.view.current_node_path()

    def export_data(self):
        """Opens a dialog to export data

        See Also
        --------
        H5BrowserUtil.export_data
        """
        try:
            file_filter = ExporterFactory.get_file_filters()
            file, selected_filter = select_file_filter(save=True, filter=file_filter)
            self.current_node_path = self.get_tree_node_path()
            if file != '':
                self.h5utils.export_data(self.current_node_path, str(file), selected_filter)

        except Exception as e:
            logger.exception(str(e))

    def save_file(self, filename=None):

        if filename is None:
            filename = select_file(save=True, ext='txt')
        if filename != '':
            self.h5utils.save_file_as(filename)  # add path ?

    def quit_fun(self):
        """
        """
        try:
            self.h5utils.close_file()
            if self.main_window is None:
                self.parent_widget.close()
            else:
                self.main_window.close()
        except Exception as e:
            logger.exception(str(e))

    def show_about(self):
        splash_path = os.path.join(os.path.split(os.path.split(__file__)[0])[0], 'splash.png')
        splash = QtGui.QPixmap(splash_path)
        self.splash_sc = QtWidgets.QSplashScreen(splash, QtCore.Qt.WindowStaysOnTopHint)
        self.splash_sc.setVisible(True)
        self.splash_sc.showMessage(f"H5Browser version {get_version('pymodaq_plugins_h5browser')}\n"
                                   f"H5Browser with Python\nWritten by Sébastien Weber",
                                   QtCore.Qt.AlignRight, QtCore.Qt.white)

    @staticmethod
    def show_log():
        webbrowser.open(logging.getLogger('pymodaq').handlers[0].baseFilename)

    @staticmethod
    def show_help():
        QtGui.QDesktopServices.openUrl(QtCore.QUrl("http://pymodaq.cnrs.fr"))

    @staticmethod
    def add_log(txt):
        logger.info(txt)

    def show_h5_attributes(self, item=None):
        try:
            self.current_node_path = self.get_tree_node_path()

            attr_dict, settings, scan_settings, pixmaps = self.h5utils.get_h5_attributes(self.current_node_path)

            for child in self.settings_attributes.settings.children():
                child.remove()
            params = []
            for attr in attr_dict:
                params.append({'title': attr, 'name': attr, 'type': 'str', 'value': attr_dict[attr],
                               'readonly': True})
            self.settings_attributes.settings.addChildren(params)

            if settings is not None:
                for child in self.settings.children():
                    child.remove()
                QtWidgets.QApplication.processEvents()  # so that the tree associated with settings updates
                params = ioxml.XML_string_to_parameter(settings)
                self.settings.addChildren(params)

            if scan_settings is not None:
                params = ioxml.XML_string_to_parameter(scan_settings)
                self.settings.addChildren(params)

            if pixmaps == []:
                self.view.pixmap_widget.setVisible(False)
            else:
                self.view.pixmap_widget.setVisible(True)
                self.show_pixmaps(pixmaps)

        except Exception as e:
            logger.exception(str(e))

    def show_pixmaps(self, pixmaps=[]):
        if self.view.pixmap_widget.layout() is None:
            self.view.pixmap_widget.setLayout(QtWidgets.QHBoxLayout())
        while 1:
            child = self.view.pixmap_widget.layout().takeAt(0)
            if not child:
                break
            child.widget().deleteLater()
            QtWidgets.QApplication.processEvents()
        labs = []
        for pix in pixmaps:
            labs.append(pngbinary2Qlabel(pix))
            self.view.pixmap_widget.layout().addWidget(labs[-1])

    def show_h5_data(self, item, with_bkg=False, plot_all=False):
        """

        Parameters
        ----------
        item
        with_bkg
        plot_all

        Returns
        -------

        """
        try:
            if item is None:
                self.current_node_path = self.get_tree_node_path()
            self.show_h5_attributes()
            node = self.h5utils.get_node(self.current_node_path)
            self.data_node_signal.emit(self.current_node_path)

            if 'data_type' in node.attrs and node.attrs['data_type'] == 'strings':
                self.view.text_list.clear()
                for txt in node.read():
                    self.view.text_list.addItem(txt)
            elif 'data_type' in node.attrs:
                data_with_axes = self.data_loader.load_data(node, with_bkg=with_bkg, load_all=plot_all)
                self.hyper_viewer.show_data(data_with_axes, force_update=True)

        except Exception as e:
            logger.exception(str(e))

    def populate_tree(self):
        """
            | Init the ui-tree and store data into calling the h5_tree_to_Qtree convertor method

            See Also
            --------
            h5tree_to_QTree, update_status
        """
        try:
            if self.h5utils.h5file is not None:
                self.view.clear()
                base_node = self.h5utils.root()
                base_tree_item, pixmap_items = h5tree_to_QTree(base_node)
                self.view.add_base_item(base_tree_item)
                self.view.add_widget_to_tree(pixmap_items)

        except Exception as e:
            logger.exception(str(e))


def main(h5file_path: Path = None):
    from pymodaq_gui.utils.utils import mkQApp
    import sys
    app = mkQApp('H5Browser')

    h5file_path_tmp = None
    parser = argparse.ArgumentParser(description="Opens HDF5 files and navigate their contents")
    parser.add_argument("-i", "--input", help="specify path to the file to be opened")
    args = parser.parse_args()

    if args.input:
        h5file_path_tmp = Path(args.input).resolve()  # Transform to absolute Path in case it is relative

        if not h5file_path_tmp.exists():
            print(f'Error: {args.input} does not exist. Opening h5browser without input file.')
            h5file_path_tmp = h5file_path

    win = QtWidgets.QMainWindow()
    dockarea = DockArea()
    # win.setCentralWidget(dockarea)
    win.setCentralWidget(dockarea)
    prog = H5Browser(parent=win, h5file_path=h5file_path_tmp, )
    win.show()
    QtWidgets.QApplication.processEvents()

    app.exec()


if __name__ == '__main__':
    main()
