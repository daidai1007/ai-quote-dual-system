// Native .NET launcher. It does not invoke PowerShell or change execution policy.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using System.Reflection;
[assembly: AssemblyTitle("AIQuoteDualSystem Legacy Upgrade Tool")]
[assembly: AssemblyFileVersion("__VERSION__")]
class LegacyClientUpgrade {
    const string VersionText="__VERSION__", PackageHash="__PACKAGE_SHA256__", ManifestHash="__MANIFEST_SHA256__";
    const string EntryHash="__ENTRY_SHA256__", FoldHash="__CASEFOLD_SHA256__", PublicKey="__PUBLIC_KEY__";
    const long PackageSize=__PACKAGE_SIZE__;
    const string Origin="http://192.168.35.212:8898", Entry="AIQuoteDualSystem_layout_v0.exe";
    static readonly JavaScriptSerializer Json=new JavaScriptSerializer { MaxJsonLength=16000000 };
    static string Home { get { return AppDomain.CurrentDomain.BaseDirectory; } }
    static string Hash(string path) { using(var sha=SHA256.Create()) using(var file=File.OpenRead(path)) return Hex(sha.ComputeHash(file)); }
    static string Hex(byte[] bytes) { return BitConverter.ToString(bytes).Replace("-","").ToLowerInvariant(); }
    static Dictionary<string,object> Read(string path) { return Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path,Encoding.UTF8)); }
    static void Write(string path,object value) { File.WriteAllText(path,Json.Serialize(value),new UTF8Encoding(false)); }
    static void Require(bool condition,string message) { if(!condition) throw new InvalidOperationException(message); }
    static string Text(Dictionary<string,object> value,string key) { return value.ContainsKey(key)?Convert.ToString(value[key]):""; }
    static void NoLinks(string path) {
        string current=Path.GetFullPath(path);
        while(!String.IsNullOrEmpty(current)) {
            if(File.Exists(current)||Directory.Exists(current)) Require((File.GetAttributes(current)&FileAttributes.ReparsePoint)==0,"不支持符号链接或目录联接。");
            current=Path.GetDirectoryName(current);
        }
    }
    static void Closed(string path) {
        try { using(File.Open(path,FileMode.Open,FileAccess.Read,FileShare.None)) {} }
        catch(IOException) { throw new InvalidOperationException("请先保存进度并关闭此目录的客户端，再运行兼容升级。"); }
    }
    static void Walk(string root,List<string> files,List<string> directories) {
        foreach(string path in Directory.GetFileSystemEntries(root)) {
            var attributes=File.GetAttributes(path);
            Require((attributes&FileAttributes.ReparsePoint)==0,"客户端包含链接；未替换程序。");
            if((attributes&FileAttributes.Directory)!=0) { directories.Add(path);Walk(path,files,directories); }
            else files.Add(path);
        }
    }
    static string Fold(string value,Dictionary<string,object> mapping) {
        var result=new StringBuilder();
        for(int index=0;index<value.Length;index++) {
            int code=Char.ConvertToUtf32(value,index);string piece=Char.ConvertFromUtf32(code);if(code>65535) index++;
            string key=code.ToString(System.Globalization.CultureInfo.InvariantCulture);
            result.Append(mapping.ContainsKey(key)?(string)mapping[key]:piece);
        }
        return result.ToString();
    }
    static void Prepare(string selected,Action<string> report) {
        string target=Path.GetFullPath(selected).TrimEnd(Path.DirectorySeparatorChar);
        Require(!target.StartsWith("\\\\")&&target!=Path.GetPathRoot(target).TrimEnd('\\'),"请选择本地现有客户端文件夹。");
        NoLinks(target);string oldEntry=Path.Combine(target,Entry);
        Require(File.Exists(oldEntry),"所选目录中没有客户端主程序。");
        string oldVersionText=FileVersionInfo.GetVersionInfo(oldEntry).FileVersion;
        var oldVersion=new Version(oldVersionText);
        if(oldVersion>=new Version(VersionText)) { report("当前已是目标版本，无需兼容升级。");return; }
        Require(oldVersion>=new Version("2026.10.20.05"),"该旧版不在本工具验证范围内。");Closed(oldEntry);
        string configPath=Path.Combine(target,"update_config.json");NoLinks(configPath);var originalConfig=Read(configPath);
        Require(originalConfig.ContainsKey("enabled")&&originalConfig["enabled"] is bool&&(bool)originalConfig["enabled"]&&
            Text(originalConfig,"channel")=="local"&&Text(originalConfig,"public_key")==PublicKey&&
            Text(originalConfig,"lan_http_origin")==Origin&&Text(originalConfig,"manifest_url")==Origin+"/stable/manifest.json",
            "更新源或验证公钥不一致；未修改客户端。");
        var config=new Dictionary<string,object>();foreach(string key in new[]{"enabled","channel","public_key","lan_http_origin","manifest_url"})config[key]=originalConfig[key];
        string manifestPath=Path.Combine(Home,"manifest.json"),foldPath=Path.Combine(Home,"python-casefold.json");
        Require(Hash(manifestPath)==ManifestHash&&Hash(foldPath)==FoldHash,"兼容工具文件哈希不匹配；未修改客户端。");
        var envelope=Read(manifestPath);var release=(Dictionary<string,object>)envelope["release"];
        string packageName="AIQuoteDualSystem-"+VersionText+".zip";
        Require(Text(release,"version")==VersionText&&Text(release,"channel")=="local"&&Text(release,"product")=="AIQuoteDualSystem"&&
            Text(release,"sha256")==PackageHash&&Convert.ToInt64(release["size"])==PackageSize&&
            Text(release,"url")==Origin+"/"+VersionText+"/"+packageName,"清单与可信固定值不一致。");
        string profile=Environment.GetEnvironmentVariable("LOCALAPPDATA");
        if(String.IsNullOrEmpty(profile))profile=Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        profile=Path.GetFullPath(profile);NoLinks(profile);
        string identity=Guid.NewGuid().ToString("N"),work=Path.Combine(profile,"AIQuoteDualSystem","compat-upgrades",identity);
        NoLinks(work);Directory.CreateDirectory(work);NoLinks(work);
        string package=Path.Combine(work,packageName),adjacent=Path.Combine(Home,packageName);
        report("正在验证程序包；不修改服务器清单。");
        if(File.Exists(adjacent)) { NoLinks(adjacent);File.Copy(adjacent,package,false); }
        else {
            var request=(HttpWebRequest)WebRequest.Create(Text(release,"url"));request.Proxy=null;request.AllowAutoRedirect=false;request.Timeout=30000;request.ReadWriteTimeout=30000;
            using(var response=(HttpWebResponse)request.GetResponse()) {
                Require(response.StatusCode==HttpStatusCode.OK&&response.ContentLength==PackageSize,"程序包响应不完整。");
                using(var input=response.GetResponseStream()) using(var output=new FileStream(package,FileMode.CreateNew)) {
                    byte[] buffer=new byte[262144];long total=0;int count;
                    while((count=input.Read(buffer,0,buffer.Length))>0) { total+=count;Require(total<=PackageSize,"程序包大小超限。");output.Write(buffer,0,count); }
                }
            }
        }
        Require(new FileInfo(package).Length==PackageSize&&Hash(package)==PackageHash,"程序包哈希/大小不匹配；未修改客户端。");
        var oldFiles=new List<string>();var oldDirectories=new List<string>();Walk(target,oldFiles,oldDirectories);
        long existingBytes=0;foreach(string file in oldFiles)existingBytes+=new FileInfo(file).Length;
        string runner=Path.Combine(work,"runner");Directory.CreateDirectory(runner);var names=new HashSet<string>(StringComparer.OrdinalIgnoreCase);var files=new List<string>();
        using(var archive=ZipFile.OpenRead(package)) {
            long expanded=0;foreach(var member in archive.Entries)expanded+=member.Length;
            var drive=new DriveInfo(Path.GetPathRoot(work));Require(drive.AvailableFreeSpace>expanded*3+existingBytes+PackageSize*2+536870912,"磁盘空间不足，未修改客户端。");
            foreach(var member in archive.Entries) {
                string name=member.FullName;
                Require(!name.EndsWith("/")&&!name.StartsWith("/")&&!name.Contains("\\")&&!name.Contains(":")&&names.Add(name),"程序包包含不安全或重复路径。");
                foreach(string part in name.Split('/'))Require(part!="."&&part!=".."&&part.Length>0,"程序包路径无效。");
                string destination=Path.GetFullPath(Path.Combine(runner,name.Replace('/',Path.DirectorySeparatorChar)));
                Require(destination.StartsWith(runner+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase),"程序包路径越界。");
                Directory.CreateDirectory(Path.GetDirectoryName(destination));member.ExtractToFile(destination,false);files.Add(name);
            }
        }
        string runnerEntry=Path.Combine(runner,Entry);
        Require(Hash(runnerEntry)==EntryHash&&FileVersionInfo.GetVersionInfo(runnerEntry).FileVersion==VersionText,"新版更新器与可信构建不一致。");
        Closed(oldEntry);string oldHash=Hash(oldEntry);
        string backup=Path.Combine(profile,"AIQuoteDualSystem","compat-backups",identity);NoLinks(backup);Directory.CreateDirectory(backup);NoLinks(backup);
        var oldHashes=new Dictionary<string,string>();report("正在完整备份原客户端并逐文件核对。");
        foreach(string directory in oldDirectories)Directory.CreateDirectory(Path.Combine(backup,directory.Substring(target.Length+1)));
        foreach(string file in oldFiles) {
            string relative=file.Substring(target.Length+1),destination=Path.Combine(backup,relative),sha=Hash(file);oldHashes[relative]=sha;
            Directory.CreateDirectory(Path.GetDirectoryName(destination));File.Copy(file,destination,false);Require(Hash(destination)==sha,"完整备份校验失败；未替换程序。");
        }
        Write(Path.Combine(backup,"backup-file-hashes.json"),oldHashes);Closed(oldEntry);
        var nowFiles=new List<string>();var nowDirs=new List<string>();Walk(target,nowFiles,nowDirs);
        Require(nowFiles.Count==oldFiles.Count&&nowDirs.Count==oldDirectories.Count,"备份期间客户端目录发生变化，未替换程序。");
        foreach(var pair in oldHashes)Require(Hash(Path.Combine(target,pair.Key))==pair.Value,"备份期间文件发生变化，未替换程序。");
        string cacheId;using(var sha=SHA256.Create())cacheId=Hex(sha.ComputeHash(Encoding.UTF8.GetBytes(Fold(target,Read(foldPath))))).Substring(0,20);
        string transaction=Path.Combine(profile,"AIQuoteDualSystem","updates",cacheId,identity);NoLinks(transaction);Directory.CreateDirectory(transaction);NoLinks(transaction);
        File.Copy(package,Path.Combine(transaction,"package.zip"),false);
        var job=new Dictionary<string,object>{{"schema",1},{"install_root",target},{"current_version",oldVersionText},{"old_exe_sha256",oldHash},
            {"config",config},{"envelope",envelope},{"files",files},{"parent_pid",Process.GetCurrentProcess().Id},{"token",Guid.NewGuid().ToString("N")},{"status","prepared"},{"workspace",""}};
        string jobPath=Path.Combine(transaction,"job.json");Write(jobPath,job);
        Write(Path.Combine(work,"compat-started.json"),new Dictionary<string,object>{{"version",VersionText},{"target",target},{"backup",backup},
            {"full_backup_files_verified",oldFiles.Count},{"transaction",jobPath},{"runner",runnerEntry},{"runner_sha256",EntryHash},
            {"installed_client_modified_by_launcher",false},{"server_written",false},{"api_deployed",false},{"database_written",false}});
        Process.Start(new ProcessStartInfo(runnerEntry,"--client-updater \""+jobPath+"\""){WorkingDirectory=runner,UseShellExecute=false,CreateNoWindow=true});
        report("备份已核对，新版更新器即将接手。请在随后出现的姓名窗口中登录。");
    }
    [STAThread] static int Main(string[] args) {
        string target="";bool noUi=false;
        for(int i=0;i<args.Length;i++) { if(args[i]=="--no-ui")noUi=true;else if(args[i]=="--client-directory"&&i+1<args.Length)target=args[++i];else return 2; }
        if(noUi) { try { Prepare(target,Console.WriteLine);return 0; } catch(Exception error) { Console.Error.WriteLine(error.Message);return 1; } }
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
        if(target.Length==0)using(var picker=new FolderBrowserDialog { Description="先保存并退出旧客户端，再选择主EXE所在文件夹",ShowNewFolderButton=false }) {
            if(picker.ShowDialog()!=DialogResult.OK)return 0;target=picker.SelectedPath;
        }
        var form=new Form { Text="AI 双报价系统 · 一次性兼容升级",Width=560,Height=180,ControlBox=false,StartPosition=FormStartPosition.CenterScreen };
        var label=new Label { Dock=DockStyle.Fill,Padding=new Padding(20),Text="正在核对旧版客户端…" };
        var bar=new ProgressBar { Dock=DockStyle.Bottom,Height=22,Style=ProgressBarStyle.Marquee };
        form.Controls.Add(label);form.Controls.Add(bar);var worker=new BackgroundWorker { WorkerReportsProgress=true };
        worker.DoWork+=(sender,eventArgs)=>Prepare(target,message=>worker.ReportProgress(0,message));
        worker.ProgressChanged+=(sender,eventArgs)=>label.Text=(string)eventArgs.UserState;
        worker.RunWorkerCompleted+=(sender,eventArgs)=>{if(eventArgs.Error!=null)MessageBox.Show(form,eventArgs.Error.Message,"兼容升级停止：未完成更新",MessageBoxButtons.OK,MessageBoxIcon.Warning);form.Close();};
        form.Shown+=(sender,eventArgs)=>worker.RunWorkerAsync();Application.Run(form);return 0;
    }
}
