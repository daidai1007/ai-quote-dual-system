import importlib.util
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOURCE = Path(__file__).resolve().parents[1]/'desktop_client/quote_monitor.py'
sys.path.insert(0, str(SOURCE.parent))
spec = importlib.util.spec_from_file_location('quote_monitor_test_adapter', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class QuoteMonitorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)/'monitor.json'
        self.received = []
        received = self.received
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                events = json.loads(self.rfile.read(int(self.headers['Content-Length'])))['events']
                received.extend(events)
                if self.headers.get('Authorization') != 'Bearer '+getattr(self.server,'expected_token','a'*43):
                    self.send_response(401);self.end_headers();return
                body = json.dumps({'results':[{'event_id':event['event_id'],'status':'accepted'} for event in events]}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self, *args): pass
        self.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.config = dict(enabled=True,environment='test',app_id='ai_quote',device_id='D-LOCAL',user_id='U-1',
                           app_version='local-1',token='a'*43,url=f'http://127.0.0.1:{self.server.server_port}/api/v1/events',
                           api_url='http://127.0.0.1:48081/api/quotes/calculate-dual')
        self.write()
    def write(self): self.path.write_text(json.dumps(self.config),encoding='utf-8')
    def create(self, user='U-1'):
        monitor = module.LocalMonitor(self.path,lambda:user)
        self.addCleanup(monitor.close)
        return monitor
    def test_persists_offline_events_then_replays_same_identifiers_after_restart(self):
        self.config['url']='http://127.0.0.1:9/api/v1/events';self.write()
        monitor=self.create()
        span=monitor.begin('save');monitor.finish(span)
        until=time.monotonic()+3
        while monitor.events.unfinished_tasks and time.monotonic()<until:time.sleep(.02)
        monitor.close()
        with closing(sqlite3.connect(self.path.parent/'monitor-spool.sqlite')) as db:
            before=[json.loads(row[0]) for row in db.execute('SELECT payload FROM pending')]
        self.assertTrue(any(event['event_type']=='operation_finished' for event in before))
        ids={event['event_id'] for event in before}
        self.config['url']=f'http://127.0.0.1:{self.server.server_port}/api/v1/events';self.write()
        resumed=self.create()
        self.assertTrue(resumed.flush(5))
        self.assertTrue(ids.issubset({event['event_id'] for event in self.received}))
    def test_expired_token_holds_events_and_rotated_token_resumes_same_operation(self):
        self.server.expected_token='b'*43
        monitor=self.create()
        span=monitor.begin('save');monitor.finish(span)
        self.assertFalse(monitor.flush(.3))
        self.config['token']='b'*43;self.write()
        self.assertTrue(monitor.flush(5))
        finished=[e for e in self.received if e['event_type']=='operation_finished']
        self.assertTrue(finished)
        self.assertEqual({e['operation_id'] for e in finished},{span['operation_id']})
        self.assertEqual(monitor.dropped,0)
    def test_name_switch_and_cancelled_late_response_cannot_misattribute_or_overwrite(self):
        monitor=self.create(user='OTHER')
        self.assertIsNone(monitor.begin('calculate'))
        monitor.identity=lambda:'U-1'
        span=monitor.begin('calculate');monitor.finish(span,'cancelled');monitor.finish(span,'success')
        self.assertTrue(monitor.flush())
        terminal=[e for e in self.received if e['event_type']=='operation_finished']
        self.assertEqual(len(terminal),1);self.assertEqual(terminal[0]['outcome'],'cancelled')
    def test_monitor_failure_never_blocks_or_repeats_business_and_bounds_memory(self):
        self.config['url']='http://127.0.0.1:9/api/v1/events';self.write()
        monitor=self.create()
        count=0;started=time.monotonic()
        span=monitor.begin('save')
        count+=1
        monitor.finish(span)
        for _ in range(5000): monitor.emit('heartbeat')
        self.assertEqual(count,1);self.assertLess(time.monotonic()-started,.6)
        self.assertLessEqual(monitor.events.qsize(),1000)
        self.assertGreater(monitor.dropped,0)
    def test_validation_is_not_technical_failure_and_no_raw_business_fields_escape(self):
        monitor=self.create()
        span=monitor.begin('save');span.update(request_outcome='denied',category='permission')
        monitor.finish(span,'failed')
        self.assertTrue(monitor.flush())
        finished=[e for e in self.received if e['event_type']=='operation_finished'][0]
        self.assertEqual(finished['outcome'],'denied')
        self.assertNotIn('error_category',finished)
        allowed={'schema_version','app_id','environment','device_id','user_id','app_version','source','event_id',
                 'event_type','occurred_at','operation','operation_id','elapsed_ms','outcome'}
        self.assertTrue(set(finished).issubset(allowed))

    def test_idempotent_write_lost_ack_is_one_pending_then_successful_operation(self):
        monitor=self.create()
        previous=module._runtime;module._runtime=monitor
        self.addCleanup(setattr,module,'_runtime',previous)
        span=monitor.begin_intent('send','same-business-request')
        span.update(category='network',request_outcome='failed')
        module.finish_attempt(span,'failed')
        self.assertTrue(monitor.flush())
        self.assertFalse(any(e['event_type']=='operation_finished' for e in self.received))
        resumed=monitor.begin_intent('send','same-business-request')
        self.assertIs(resumed,span)
        module.finish_attempt(resumed,'success')
        module.finish_attempt(monitor.begin_intent('send','same-business-request'),'success')
        self.assertTrue(monitor.flush())
        starts=[e for e in self.received if e['event_type']=='operation_started']
        finals=[e for e in self.received if e['event_type']=='operation_finished']
        self.assertEqual(len(starts),1);self.assertEqual(len(finals),1)
        self.assertEqual(finals[0]['outcome'],'success')
        self.assertEqual(finals[0]['operation_id'],starts[0]['operation_id'])

    def test_repeated_attempts_in_one_worker_keep_one_request_group(self):
        self.config['api_url']=f'http://127.0.0.1:{self.server.server_port}/api/test'
        self.write();monitor=self.create()
        previous=module._runtime;module._runtime=monitor
        self.addCleanup(setattr,module,'_runtime',previous)
        span=monitor.begin('export')
        module._thread.span=span;module._thread.request_groups={}
        self.addCleanup(setattr,module._thread,'span',None)
        self.addCleanup(setattr,module._thread,'request_groups',None)
        for _ in range(2):
            request=module.urllib.request.Request(self.config['api_url'],data=b'{"events":[]}',
              headers={'Authorization':'Bearer '+'a'*43,'Content-Type':'application/json'})
            with module.monitored_urlopen(request,timeout=2) as response:response.read()
        monitor.finish(span)
        self.assertTrue(monitor.flush())
        requests=[e for e in self.received if e['event_type']=='request_finished']
        self.assertEqual(len(requests),2)
        self.assertEqual(len({e['request_id'] for e in requests}),1)

    def await_state(self, monitor, state):
        until=time.monotonic()+4
        while time.monotonic()<until:
            if monitor.state==state:return
            time.sleep(.02)
        self.fail('State did not become '+state)

    def test_disabled_startup_and_hot_stop_never_collect_or_send_then_resume_same_backlog(self):
        self.config['enabled']=False;self.write()
        monitor=self.create()
        time.sleep(.3)
        self.assertIsNone(monitor.begin('save'))
        monitor.emit('heartbeat');self.assertEqual(len(self.received),0)
        self.config['enabled']=True;self.write();self.await_state(monitor,'active')
        span=monitor.begin('save');monitor.finish(span);self.assertTrue(monitor.flush())
        self.config['enabled']=False;self.write();self.await_state(monitor,'disabled')
        time.sleep(.3);count=len(self.received)
        self.assertIsNone(monitor.begin('contract'))
        monitor.emit('heartbeat');time.sleep(.4)
        self.assertEqual(len(self.received),count)
        self.config['enabled']=True;self.write();self.await_state(monitor,'active')
        resumed=monitor.begin('open');monitor.finish(resumed);self.assertTrue(monitor.flush())
        self.assertTrue(any(e.get('operation_id')==resumed['operation_id'] for e in self.received))

    def test_intents_and_terminal_elapsed_survive_restart_without_a_second_terminal(self):
        monitor=self.create()
        span=monitor.begin_intent('send','persisted-id');monitor.finish(span)
        self.assertTrue(monitor.flush());monitor.close()
        count=len([e for e in self.received if e['event_type']=='operation_finished'])
        resumed=self.create()
        old=resumed.begin_intent('send','persisted-id')
        self.assertEqual(old['operation_id'],span['operation_id']);self.assertTrue(old['ended'])
        resumed.finish(old);self.assertTrue(resumed.flush())
        self.assertEqual(count,len([e for e in self.received if e['event_type']=='operation_finished']))

    def test_unconfirmed_intent_restart_keeps_operation_and_mapping_changes_suspend_collection(self):
        monitor=self.create()
        span=monitor.begin_intent('contract','pending-id')
        self.assertTrue(monitor.flush());monitor.close()
        resumed=self.create();retry=resumed.begin_intent('contract','pending-id')
        self.assertEqual(retry['operation_id'],span['operation_id']);self.assertFalse(retry['ended'])
        resumed.finish(retry);self.assertTrue(resumed.flush())
        self.config['device_id']='other';self.write()
        self.await_state(resumed,'configuration_unavailable');self.assertIsNone(resumed.begin('save'))

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI is verified by the Windows CI job')
    def test_production_secret_roundtrip_is_user_protected_and_http_is_rejected(self):
        import monitor_settings as settings
        secret=self.path.parent/'credential.dpapi'
        value=dict(app_id='ai_quote',environment='production',device_id='D',user_id='U',renewal_secret='s'*43)
        settings.save_secret(secret,value)
        self.assertEqual(settings.load_secret(secret),value)
        self.assertNotIn('s'*43,secret.read_text())
        self.config.update(profile='production',environment='production')
        self.write()
        with self.assertRaises(ValueError):module._config(self.path)

    def test_hot_stop_preserves_unacknowledged_backlog_and_resumes_exact_event_ids(self):
        self.server.expected_token='b'*43
        monitor=self.create();span=monitor.begin_intent('send','stopped-backlog');monitor.finish(span)
        self.assertFalse(monitor.flush(.3))
        self.config['enabled']=False;self.write();self.await_state(monitor,'disabled')
        with closing(sqlite3.connect(monitor.spool)) as db:
            ids={row[0] for row in db.execute('SELECT id FROM pending')}
        self.assertTrue(ids)
        self.config.update(enabled=True,token='b'*43);self.write()
        self.await_state(monitor,'active');self.assertTrue(monitor.flush())
        self.assertTrue(ids.issubset({e['event_id'] for e in self.received}))

    def test_monitor_redirect_is_refused_without_forwarding_credential(self):
        class Redirect:
            def get_full_url(self):return 'https://monitor.example.invalid/api/v1/events'
        with self.assertRaises(module.urllib.error.URLError):
            module._NoMonitorRedirect().redirect_request(Redirect(),None,302,'',{},'https://other.example.invalid/steal')

if __name__=='__main__':unittest.main()
