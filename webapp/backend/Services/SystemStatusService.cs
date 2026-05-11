using System;
using System.Collections.Concurrent;

namespace LightningTracker.WebApi.Services;

public class SystemStatusService
{
    public SyncStatus LastSync { get; private set; } = new();
    public NowcastStatus LastNowcast { get; private set; } = new();
    public ConcurrentQueue<string> RecentLogs { get; } = new();

    public void UpdateSync(int files, int skipped, int flashes, int events, string? error = null)
    {
        LastSync = new SyncStatus
        {
            Timestamp = DateTime.UtcNow,
            FilesProcessed = files,
            FilesSkipped = skipped,
            TotalFlashes = flashes,
            TotalEvents = events,
            LastError = error,
            IsRunning = false
        };
        AddLog($"[SYNC] Concluído: {files} novos arquivos, {flashes} raios.");
    }

    public void SetSyncRunning(bool running)
    {
        LastSync.IsRunning = running;
        if (running) AddLog("[SYNC] Iniciando sincronização...");
    }

    public void UpdateNowcast(int cells, int impacts, string? error = null)
    {
        LastNowcast = new NowcastStatus
        {
            Timestamp = DateTime.UtcNow,
            CellCount = cells,
            ImpactCount = impacts,
            LastError = error,
            IsRunning = false
        };
        AddLog($"[NOWCAST] Concluído: {cells} células, {impacts} impactos.");
    }

    public void SetNowcastRunning(bool running)
    {
        LastNowcast.IsRunning = running;
        if (running) AddLog("[NOWCAST] Iniciando motor de previsão...");
    }

    public void AddLog(string message)
    {
        var timestamp = DateTime.Now.ToString("HH:mm:ss");
        RecentLogs.Enqueue($"[{timestamp}] {message}");
        while (RecentLogs.Count > 50) RecentLogs.TryDequeue(out _);
    }
}

public class SyncStatus
{
    public DateTime Timestamp { get; set; }
    public int FilesProcessed { get; set; }
    public int FilesSkipped { get; set; }
    public int TotalFlashes { get; set; }
    public int TotalEvents { get; set; }
    public string? LastError { get; set; }
    public bool IsRunning { get; set; }
}

public class NowcastStatus
{
    public DateTime Timestamp { get; set; }
    public int CellCount { get; set; }
    public int ImpactCount { get; set; }
    public string? LastError { get; set; }
    public bool IsRunning { get; set; }
}
