"""Prepare a one-time legacy upgrade launcher around an unchanged signed client."""
from pathlib import Path
import argparse,json,shutil,subprocess,sys,zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
from client_update_core import ENTRY,digest,read_json,verify_manifest


def prepare(manifest,update_config,output,entry_sha256):
    manifest,output=Path(manifest).resolve(),Path(output).resolve()
    if output.exists():raise FileExistsError('Use a fresh tool directory')
    config=read_json(update_config)
    release=verify_manifest(read_json(manifest),config)
    origin='http://192.168.35.212:8898'
    assert config['channel']=='local' and config['lan_http_origin']==origin
    assert config['manifest_url']==origin+'/stable/manifest.json'
    version=release['version'];name=f'AIQuoteDualSystem-{version}.zip'
    package=manifest.parent/name
    assert release['url']==origin+'/'+version+'/'+name
    assert package.stat().st_size==release['size'] and digest(package)==release['sha256']
    with zipfile.ZipFile(package) as archive:
        import hashlib
        assert hashlib.sha256(archive.read(ENTRY)).hexdigest()==entry_sha256
    output.mkdir(parents=True)
    shutil.copy2(manifest,output/'manifest.json')
    fold={str(n):chr(n).casefold() for n in range(0x110000) if chr(n).casefold()!=chr(n)}
    (output/'python-casefold.json').write_text(json.dumps(fold,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    replacements=dict(VERSION=version,PACKAGE_SHA256=release['sha256'],PACKAGE_SIZE=str(release['size']),
        MANIFEST_SHA256=digest(manifest),ENTRY_SHA256=entry_sha256,
        CASEFOLD_SHA256=digest(output/'python-casefold.json'),PUBLIC_KEY=config['public_key'])
    text=(ROOT/'packaging/LegacyClientUpgrade.template.cs').read_text(encoding='utf-8-sig')
    for key,value in replacements.items():text=text.replace('__'+key+'__',value)
    assert '__VERSION__' not in text and '__PACKAGE_SHA256__' not in text
    source=output/'LegacyClientUpgrade.cs';source.write_text(text,encoding='utf-8-sig')
    entry=output/'AIQuoteDualSystem_CompatUpgrade.exe'
    command=['C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe','/nologo','/target:winexe','/platform:x64','/optimize+',
        '/out:'+str(entry),'/r:System.Windows.Forms.dll','/r:System.Web.Extensions.dll',
        '/r:System.IO.Compression.dll','/r:System.IO.Compression.FileSystem.dll',str(source)]
    subprocess.run(command,check=True,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    entry.with_name(entry.name+'.config').write_text('<?xml version="1.0" encoding="utf-8"?><configuration><startup><supportedRuntime version="v4.0" sku=".NETFramework,Version=v4.8"/></startup><runtime><AppContextSwitchOverrides value="Switch.System.IO.UseLegacyPathHandling=false;Switch.System.IO.BlockLongPaths=false"/></runtime></configuration>',encoding='utf-8')
    (output/'使用说明.txt').write_text(f'''旧版一次性兼容升级至 {version}

用途：旧客户端内置更新器固定等待30秒，无法等待新版姓名登录。本工具使用已经验收的新版更新器完成一次升级，之后可正常使用客户端内置更新。
本工具不会修改服务器清单，也不部署API或执行数据库迁移。

操作：
1. 在旧客户端保存本机进度，并退出所有使用该安装目录的客户端。
2. 将本工具完整解压到独立文件夹，核对管理员提供的SHA256。
3. 双击 AIQuoteDualSystem_CompatUpgrade.exe，选择现有客户端主EXE所在文件夹。工具是独立.NET程序，不调用PowerShell脚本。
4. 工具先验证程序包和公钥绑定，再完整备份现有客户端目录。程序包若不在工具旁边，会从已绑定内网源下载。
5. 等待新版更新器启动，然后在新客户端姓名窗口中输入本人姓名。等待输入不计入主窗口30秒时限，提交后才开始检查。
6. 成功后使用原客户端路径或原快捷方式启动；备份和更新日志保留。失败由更新器恢复旧版，请保留全部现场。

更新包：{origin}/{version}/{name}
需要离线操作时，将此ZIP放在兼容工具EXE旁边，工具仍强制验证固定SHA256、大小、清单和验证公钥。
用户配置、订单、图纸、备份不会打包分发；工具在旧电脑本地创建完整备份，不上传业务文件。
本工具不能读取未保存的工作内容，须先保存并退出旧客户端。它不强制结束操作人员进程。
如果系统阻止程序，请联系管理员核实和按公司政策处理；不要关闭防护、添加排除项或绕过安全策略。
首次使用先在一台旧测试电脑验收，再逐台处理。未完成兼容升级的旧电脑不要直接用旧内置更新器安装本版本。
''',encoding='utf-8-sig')
    files={p.name:digest(p) for p in output.iterdir() if p.is_file()}
    (output/'SHA256SUMS.txt').write_text(''.join(sha+'  '+name+'\n' for name,sha in sorted(files.items())),encoding='utf-8-sig')
    return dict(version=version,package_sha256=release['sha256'],entry_sha256=entry_sha256,
        manifest_sha256=digest(manifest),files=files,casefold_entries=len(fold),
        client_rebuilt=False,launcher_compiled=True,powershell_invoked=False,server_written=False,source_package_unchanged=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','update-config','output','entry-sha256'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.manifest,args.update_config,args.output,args.entry_sha256),ensure_ascii=False,indent=2))
