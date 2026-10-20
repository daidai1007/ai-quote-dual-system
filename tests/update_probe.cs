// A tiny LOCAL TEST application; never contains quotation/business code.
using System;
using System.IO;
using System.Threading;
class UpdateProbe {
    static void Main(string[] args) {
        var lines = File.ReadAllLines(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "_internal", "version.txt"));
        if (lines.Length > 1 && lines[1] == "fail") Environment.Exit(3);
        var health = Environment.GetEnvironmentVariable("AI_QUOTE_UPDATE_HEALTH_FILE");
        var token = Environment.GetEnvironmentVariable("AI_QUOTE_UPDATE_HEALTH_TOKEN");
        if (!String.IsNullOrEmpty(health)) {
            File.WriteAllText(health, "{\"token\":\"" + token + "\",\"version\":\"" + lines[0] + "\"}");
        }
        Thread.Sleep(60000);
    }
}
