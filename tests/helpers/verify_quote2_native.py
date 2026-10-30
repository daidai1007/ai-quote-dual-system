"""Real spreadsheet edits and A4 PDF output, with a private local UNO pipe."""
from pathlib import Path
import json,sys,subprocess,time,uuid
import uno
from com.sun.star.beans import PropertyValue

source,destination,pdf_path,request_path,report_path=map(Path,sys.argv[1:6])
pipe='quote2_'+uuid.uuid4().hex;profile=destination.parent/'lo-profile'
office=Path(sys.executable).parent/'soffice.exe'
process=subprocess.Popen([str(office),'-env:UserInstallation='+profile.resolve().as_uri(),'--headless','--norestore','--nodefault','--nofirststartwizard','--accept=pipe,name='+pipe+';urp;StarOffice.ComponentContext'],creationflags=subprocess.CREATE_NO_WINDOW)
desktop=doc=None
def prop(name,value):
 p=PropertyValue();p.Name=name;p.Value=value;return p
try:
 context=uno.getComponentContext();resolver=context.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver',context);deadline=time.monotonic()+25
 while True:
  try:remote=resolver.resolve('uno:pipe,name='+pipe+';urp;StarOffice.ComponentContext');break
  except Exception:
   if time.monotonic()>deadline:raise
   time.sleep(.15)
 desktop=remote.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop',remote)
 doc=desktop.loadComponentFromURL(source.resolve().as_uri(),'_blank',0,(prop('Hidden',True),prop('MacroExecutionMode',0),prop('UpdateDocMode',3)))
 assert doc is not None and doc.isAutomaticCalculationEnabled()
 request=json.loads(request_path.read_text(encoding='utf8'));quote=doc.Sheets.getByName('报价');public=doc.Sheets.getByName('报价2')
 for address,value in request['edits'].items():
  cell=quote.getCellRangeByName(address)
  cell.setValue(value) if isinstance(value,(int,float)) else cell.setString(value)
 values={a:public.getCellRangeByName(a).getValue() for a in request['numbers']}
 strings={a:public.getCellRangeByName(a).getString() for a in request['strings']}
 report_path.write_text(json.dumps({'automatic':True,'values':values,'strings':strings},ensure_ascii=False),encoding='utf8')
 doc.storeAsURL(destination.resolve().as_uri(),(prop('FilterName','Calc MS Excel 2007 XML'),prop('Overwrite',True)))
 # Hide other sheets only in the PDF session, after saving the unchanged
 # workbook's sheet visibility. This exports exactly the requested A4 sheet.
 doc.CurrentController.setActiveSheet(public)
 for sheet in doc.Sheets:
  if sheet.Name!='报价2':sheet.IsVisible=False
 doc.storeToURL(pdf_path.resolve().as_uri(),(prop('FilterName','calc_pdf_Export'),prop('Overwrite',True)))
finally:
 if doc is not None:doc.close(True)
 if desktop is not None:desktop.terminate()
 try:process.wait(timeout=10)
 except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
