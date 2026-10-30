"""Exercise real Calc cell edits on synthetic quotes via a private local pipe."""
from pathlib import Path
import sys,json,subprocess,time,uuid
import uno
from com.sun.star.beans import PropertyValue

source,destination,edits_path,report_path=map(Path,sys.argv[1:5])
name='quote_export_'+uuid.uuid4().hex
profile=destination.parent/'lo-profile'
office=Path(sys.executable).parent/'soffice.exe'
process=subprocess.Popen([str(office),'-env:UserInstallation='+profile.resolve().as_uri(),'--headless','--norestore','--nodefault','--nofirststartwizard','--accept=pipe,name='+name+';urp;StarOffice.ComponentContext'],creationflags=subprocess.CREATE_NO_WINDOW)
desktop=None;doc=None
def prop(name,value):
 p=PropertyValue();p.Name=name;p.Value=value;return p
try:
 context=uno.getComponentContext();resolver=context.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver',context)
 deadline=time.monotonic()+25
 while True:
  try:remote=resolver.resolve('uno:pipe,name='+name+';urp;StarOffice.ComponentContext');break
  except Exception:
   if time.monotonic()>deadline:raise
   time.sleep(.15)
 desktop=remote.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop',remote)
 doc=desktop.loadComponentFromURL(source.resolve().as_uri(),'_blank',0,(prop('Hidden',True),prop('MacroExecutionMode',0),prop('UpdateDocMode',3)))
 if doc is None:raise RuntimeError('Cannot open synthetic quotation')
 assert doc.isAutomaticCalculationEnabled(),'Generated workbook must open with automatic calculation'
 data=json.loads(edits_path.read_text(encoding='utf8'));sheet=doc.Sheets.getByName('报价')
 for address,value in data['edits'].items():sheet.getCellRangeByName(address).setValue(value)
 # Read immediately after native edits: do not calculateAll() to mask a
 # workbook that fails to update automatically when the operator types.
 observed={address:sheet.getCellRangeByName(address).getValue() for address in data['check']}
 report_path.write_text(json.dumps({'automatic':True,'values':observed}),encoding='utf8')
 doc.storeAsURL(destination.resolve().as_uri(),(prop('FilterName','Calc MS Excel 2007 XML'),prop('Overwrite',True)))
finally:
 if doc is not None:doc.close(True)
 if desktop is not None:desktop.terminate()
 try:process.wait(timeout=10)
 except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
