"""Actual V3 close chain and real blue dialog button, offline transport only."""
import unittest
from unittest.mock import patch
from PySide6.QtCore import QThread,QTimer,Qt
from PySide6.QtTest import QTest
import verify_name_login as fixture
import name_login
import scheme2_ui as ui


class DiscardClose(unittest.TestCase):
    def setUp(self):
        fixture.LoginTests.setUp(self)
        name_login.set_session(fixture.person('本机关闭测试人员'))
        self.w=fixture.LoginTests.window(self)
        self.w._quote_scheme_save_timer.stop();self.w._quote_scheme_id=''
        self.w._scheme2_dirty=True;self.prompts=0;self.accept=True
        original=ui._SchemeConfirmDialog.exec
        def execute(dialog):
            self.prompts+=1
            # A second unexpected prompt is rejected to expose the regression,
            # never hanging the offline test in a nested dialog event loop.
            button=dialog.accept_button if self.accept and self.prompts==1 else dialog.reject_button
            QTimer.singleShot(0,lambda:QTest.mouseClick(button,Qt.MouseButton.LeftButton))
            return original(dialog)
        p=patch.object(ui._SchemeConfirmDialog,'exec',execute);p.start();self.addCleanup(p.stop)

    def tearDown(self):
        self.w._scheme2_dirty=False
        self.w.quote_drawing_preview._workers=[]
        self.w._quote_scheme_save_worker=None
        self.w._quote_scheme_registration_busy=False
        self.w._quote_scheme_export_context=None
        self.w.contract_management.unsaved=False
        self.w.contract_management.profile_dirty=False
        fixture.LoginTests.tearDown(self)

    def test_blue_button_closes_an_idle_real_window(self):
        self.assertTrue(self.w.close());self.assertFalse(self.w.isVisible());self.assertEqual(self.prompts,1)

    def test_continue_editing_keeps_unsaved_content_and_enabled_controls(self):
        self.w.scheme2_name_edit.setText('尚未加入清单的本机测试配置')
        self.accept=False
        self.assertFalse(self.w.close());self.assertTrue(self.w.isVisible())
        self.assertTrue(self.w._scheme2_dirty);self.assertTrue(self.w.centralWidget().isEnabled())
        self.assertEqual(self.w.scheme2_name_edit.text(),'尚未加入清单的本机测试配置')
        self.assertEqual(self.prompts,1)

    def test_core_background_shutdown_retries_without_a_second_discard_dialog(self):
        running=[True]
        class Worker:
            def requestInterruption(worker):QTimer.singleShot(40,lambda:running.__setitem__(0,False))
        worker=Worker()
        self.w.active_background_threads=lambda:[worker] if running[0] else []
        self.assertFalse(self.w.close())
        fixture.wait(lambda:not self.w.isVisible())
        self.assertEqual(self.prompts,1)

    def test_preview_shutdown_retries_after_workers_finish(self):
        owner=self.w.quote_drawing_preview
        class Worker:
            def requestInterruption(worker):QTimer.singleShot(40,lambda:setattr(owner,'_workers',[]))
        owner._workers=[Worker()]
        self.assertFalse(self.w.close())
        fixture.wait(lambda:not self.w.isVisible())
        self.assertEqual(self.prompts,1)

    def test_real_qthread_is_interrupted_and_finishes_before_window_closes(self):
        class InFlight(QThread):
            def run(worker):
                worker.msleep(180)  # An in-flight call must finish safely.
        worker=InFlight(self.w)
        self.addCleanup(lambda:worker.wait(2000))
        worker.start();fixture.wait(worker.isRunning)
        self.assertFalse(self.w.close())
        self.assertTrue(worker.isInterruptionRequested())
        self.assertTrue(self.w.isVisible())
        self.assertFalse(self.w.centralWidget().isEnabled())
        fixture.wait(lambda:not self.w.isVisible())
        self.assertFalse(worker.isRunning());self.assertEqual(self.prompts,1)
        self.assertTrue(self.w._scheme2_dirty)  # Discard is not a save.

    def test_pending_scheme_save_still_blocks_before_discard_confirmation(self):
        class Saving:
            def isRunning(self):return True
        self.w._quote_scheme_save_worker=Saving()
        with patch.object(ui.QMessageBox,'information'):
            self.assertFalse(self.w.close())
        self.assertTrue(self.w.isVisible());self.assertEqual(self.prompts,0)
        self.assertTrue(self.w._scheme2_dirty)

    def test_export_registration_still_blocks_before_discard_confirmation(self):
        self.w._quote_scheme_registration_busy=True
        with patch.object(ui.QMessageBox,'information'):
            self.assertFalse(self.w.close())
        self.assertTrue(self.w.isVisible());self.assertEqual(self.prompts,0)

    def test_unsaved_contract_and_customer_profile_can_still_cancel(self):
        page=self.w.contract_management
        for field in ('profile_dirty','unsaved'):
            with self.subTest(field=field):
                setattr(page,field,True)
                with patch.object(ui.QMessageBox,'question',return_value=ui.QMessageBox.StandardButton.Cancel):
                    self.assertFalse(self.w.close())
                self.assertTrue(getattr(page,field));self.assertEqual(self.prompts,0)
                self.assertTrue(self.w.centralWidget().isEnabled())
                setattr(page,field,False)

    def test_update_launch_failure_restores_editing_and_requires_fresh_consent(self):
        with patch.object(self.w.client_updates,'launch_pending',side_effect=RuntimeError('synthetic failure')), \
                patch.object(self.w.client_updates,'show_dialog'):
            self.assertFalse(self.w.close())
        self.assertTrue(self.w.isVisible());self.assertTrue(self.w.centralWidget().isEnabled())
        self.assertTrue(self.w._scheme2_dirty)
        self.assertFalse(self.w._scheme2_discard_close_approved)
        self.accept=False;self.w.close();self.assertEqual(self.prompts,2)

    def test_a_later_close_guard_can_cancel_and_restore_editing(self):
        running=[True]
        class Worker:
            def requestInterruption(worker):QTimer.singleShot(40,lambda:running.__setitem__(0,False))
        worker=Worker();self.w.active_background_threads=lambda:[worker] if running[0] else []
        calls=[]
        def before(event):
            calls.append(True)
            if len(calls)>1:event.ignore();return False
            return True
        with patch.object(self.w.client_updates,'before_close',before):
            self.assertFalse(self.w.close())
            fixture.wait(lambda:len(calls)>1)
            QTest.qWait(150)
        self.assertTrue(self.w.isVisible());self.assertTrue(self.w.centralWidget().isEnabled())
        self.assertTrue(self.w._scheme2_dirty)
        self.assertFalse(getattr(self.w,'_scheme2_discard_close_approved',False))
        self.accept=False;self.w.close();self.assertEqual(self.prompts,2)


if __name__=='__main__':unittest.main(verbosity=2)
