import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import launcher
import install

class LauncherTests(unittest.TestCase):
    def test_dirty_checkout_is_not_pulled(self):
        with patch.object(launcher.shutil if hasattr(launcher, 'shutil') else __import__('shutil'), 'which', return_value='/bin/uv'), patch.object(launcher, 'git', side_effect=[str(launcher.ROOT), ' M study.json']), patch.object(launcher.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'local changes'):
                launcher.update()
            run.assert_not_called()

    def test_launcher_preserves_arguments_and_directory(self):
        with patch.object(launcher.sys, 'argv', ['regrowth', 'validate', '--study', '/path with spaces/study.json']), patch.object(launcher.subprocess, 'call', return_value=0) as call:
            self.assertEqual(launcher.main(), 0)
            self.assertEqual(call.call_args.args[0][-3:], ['validate', '--study', '/path with spaces/study.json'])
            self.assertNotIn('cwd', call.call_args.kwargs)

    def test_install_does_not_overwrite_another_command(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'regrowth';target.write_text('existing command')
            with patch.object(install.sys, 'platform', 'linux'), patch.object(install.shutil, 'which', return_value='/bin/uv'), patch.object(install.subprocess, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'unrelated launcher'):
                    install.install(Path(temp))
                self.assertEqual(target.read_text(), 'existing command')
                run.assert_not_called()
