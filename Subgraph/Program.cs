// Minimal subgraph: one subscription emitting on a timer, plus the query type Fusion requires.
//
//   dotnet run                    serve on http://127.0.0.1:5311/graphql
//   dotnet run -- print-schema    write the SDL to stdout and exit (used by compose.sh)
//
// TICK_SECONDS controls the event interval; 0 emits nothing at all. A silent subgraph is the
// realistic case — subscriptions that carry occasional business events sit idle most of the time,
// and that is precisely when a client cannot tell a live subscription from a dead one.
using HotChocolate.Execution;
using HotChocolate.Subscriptions;

if (args.Contains("print-schema"))
{
    // Building the schema without a web host keeps composition offline: no port to bind, nothing to
    // start and stop, and the SDL cannot drift from what the server actually serves.
    var schema = await new ServiceCollection()
                       .AddGraphQLServer()
                       .AddQueryType<Query>()
                       .AddSubscriptionType<Subscriptions>()
                       .AddInMemorySubscriptions()
                       .BuildSchemaAsync();

    Console.Out.Write(schema.ToString());
    Console.Out.Flush();
    return;
}

var builder = WebApplication.CreateBuilder(args);

builder.WebHost.UseUrls("http://127.0.0.1:5311");

builder.Services
       .AddGraphQLServer()
       .AddQueryType<Query>()
       .AddSubscriptionType<Subscriptions>()
       .AddInMemorySubscriptions()
       .ModifyRequestOptions(o => o.IncludeExceptionDetails = true);

builder.Services.AddHostedService<Ticker>();

var app = builder.Build();
app.MapGraphQL("/graphql");
app.Run();

public sealed class Query
{
    public string Ping() => "pong";
}

public sealed class Subscriptions
{
    [Subscribe]
    [Topic("tick")]
    public Tick OnTick([EventMessage] Tick tick) => tick;
}

public sealed record Tick(int Number, string At);

/// <summary>
/// Emits an event on an interval so a healthy stream is visibly delivering. Set TICK_SECONDS=0 to
/// emit nothing: the client then receives only gateway pings, and a healthy idle subscription
/// becomes indistinguishable from a dead one — the customer's exact position.
/// </summary>
internal sealed class Ticker(ITopicEventSender sender, ILogger<Ticker> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var interval = int.TryParse(Environment.GetEnvironmentVariable("TICK_SECONDS"), out var seconds)
                           ? seconds
                           : 5;

        if (interval <= 0)
        {
            logger.LogInformation("TICK_SECONDS={Interval}: emitting no events. The client will see only pings.", interval);
            return;
        }

        var number = 0;
        while (!stoppingToken.IsCancellationRequested)
        {
            await Task.Delay(TimeSpan.FromSeconds(interval), stoppingToken);
            number++;
            logger.LogInformation("Publishing tick {Number}", number);
            await sender.SendAsync("tick", new Tick(number, DateTimeOffset.UtcNow.ToString("HH:mm:ss")), stoppingToken);
        }
    }
}
