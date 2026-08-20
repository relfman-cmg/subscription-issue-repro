// Minimal Fusion v15 gateway: the federation and nothing else.
var builder = WebApplication.CreateBuilder(args);

builder.WebHost.UseUrls("http://127.0.0.1:5310");

// Must match "clientName" in Subgraph/schema/subgraph-config.json — that is how Fusion resolves
// the subgraph's HttpClient. Without it the gateway cannot reach the subgraph at all.
builder.Services.AddHttpClient("Subgraph");

// Nitro runs in a browser, so without CORS it reports the endpoint as unreachable even though the
// server answered — while the same request from a shell client succeeds.
builder.Services.AddCors();

builder.Services
       .AddFusionGatewayServer()
       .ConfigureFromFile(System.IO.Path.Combine(AppContext.BaseDirectory, "gateway.fgp"))
       .CoreBuilder
       // Otherwise the gateway reports "Unknown subscription error" and swallows the cause.
       .ModifyRequestOptions(o => o.IncludeExceptionDetails = true);

var app = builder.Build();

app.UseCors(c => c.AllowAnyHeader().AllowAnyMethod().AllowAnyOrigin());

// The short keep-alive makes the point of the repro quick to see: these pings are generated here,
// by a healthy gateway, and keep arriving long after the subgraph has stopped responding.
app.UseWebSockets(new WebSocketOptions { KeepAliveInterval = TimeSpan.FromSeconds(15) });

// One path serves HTTP, the WebSocket endpoint, the SDL and the IDE. Splitting them dropped
// /graphql/schema.graphql, which is what Nitro fetches to resolve the schema.
app.MapGraphQL("/graphql");
app.Run();
