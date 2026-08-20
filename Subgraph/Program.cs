// Minimal subgraph: one subscription, plus the query type Fusion requires.
//
//   dotnet run                    serve on http://127.0.0.1:5311/graphql
//   dotnet run -- print-schema    write the SDL to stdout and exit (used by compose.sh)
//
// By default it emits nothing at all. That is the realistic case: subscriptions carrying occasional
// business events sit idle most of the time, and that is exactly when a client cannot tell a live
// subscription from a dead one. Set TICK_SECONDS=5 to watch delivery working before the freeze.
using HotChocolate.Execution;
using HotChocolate.Subscriptions;

if (args.Contains("print-schema"))
{
    // Building the schema without a web host keeps composition offline, and the SDL cannot drift
    // from what the server actually serves.
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

internal sealed class Ticker(ITopicEventSender sender, ILogger<Ticker> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var interval = int.TryParse(Environment.GetEnvironmentVariable("TICK_SECONDS"), out var seconds)
                           ? seconds
                           : 0;

        if (interval <= 0)
        {
            logger.LogInformation("Emitting no events (TICK_SECONDS={Interval}). The client will see only pings.", interval);
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
