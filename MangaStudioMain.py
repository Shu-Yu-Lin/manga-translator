# ===============================================================
# Manga Translation Studio - Main Entry Point
#
# Author: User & Gemini Collaboration
#
# Description: This file is the main entry point for the
#              application. It configures the system path
#              and launches the main UI window.
# ===============================================================

import atexit
import os
import shutil
import socket
import subprocess
import sys
from PySide6.QtWidgets import QApplication, QMessageBox

# --- Path Configuration ---
# This is crucial for the modular structure to work correctly.
# It ensures that Python can find the 'app' module inside the 'MangaStudio_Data' directory.

# Get the absolute path of the directory where this script is located (the project root)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Define the path to the directory containing our application source code
APP_SOURCE_DIR = os.path.join(BASE_DIR, "MangaStudio_Data")

# Add the source directory to the Python system path.
# This allows us to use `from app.ui.library_window import ...`
sys.path.insert(0, APP_SOURCE_DIR)


# --- Application Launch ---
try:
    # Now that the path is configured, we can import the main application class.
    from app.ui.library_window import LibraryWindow
except ImportError as e:
    # A QApplication instance is needed to show a QMessageBox.
    # We create a dummy app here just for the error message.
    error_app = QApplication(sys.argv)
    QMessageBox.critical(
        None,
        "Fatal Import Error",
        "Could not import the main application class. "
        "Please check that the following structure is correct:\n\n"
        "MangaStudio_Data -> app -> ui -> library_window.py\n\n"
        f"Error: {e}"
    )
    sys.exit(1)


def start_ollama():
    """Start `ollama serve` if nothing listens on 11434. Returns False if Ollama is missing."""
    try:
        socket.create_connection(("localhost", 11434), timeout=0.5).close()
        return True  # already running (not ours, so we don't stop it)
    except OSError:
        pass
    # Finder-launched apps get a minimal PATH, so also check the usual install dirs.
    exe = shutil.which("ollama", path=os.environ.get("PATH", "") + ":/usr/local/bin:/opt/homebrew/bin")
    if not exe:
        return False
    proc = subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    atexit.register(proc.terminate)
    return True


if __name__ == "__main__":
    try:
        # 1. Create the PySide Application instance
        app = QApplication(sys.argv)

        if not start_ollama():
            QMessageBox.warning(None, "Ollama not found",
                                "Install Ollama and run `ollama pull gemma4:e4b`. Translation will fail until then.")

        # 2. Create an instance of our main window
        #    (The TranslatorStudioApp class will be a PySide window now)
        main_window = LibraryWindow()

        # 3. Show the window
        main_window.show()

        # 4. Start the application's event loop
        sys.exit(app.exec())

    except Exception as e:
        import traceback
        
        error_title = "Critical Application Error"
        error_message = (
            "The application encountered a critical error and had to shut down.\n\n"
            f"Error Type: {type(e).__name__}\n"
            f"Error Details: {e}\n\n"
            "Please check the console output for the full traceback."
        )
        
        print(f"---! {error_title.upper()} !---")
        traceback.print_exc()
        print("---------------------------------")
        
        # We still need a QApplication to show the error message.
        # Create one if it doesn't exist yet.
        error_app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, error_title, error_message)
        sys.exit(1)