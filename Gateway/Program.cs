// Minimal Fusion v15 gateway. Nothing here but the federation itself — no auth, no tenancy,
// no other subgraphs — so a hang can only be attributed to the subgraph subscription transport.
var builder = WebApplication.CreateBuilder(args);

builder.WebHost.UseUrls("http://127.0.0.1:5310");

// The name matches "clientName" in Subgraph/schema/subgraph-config.json. Fusion resolves the
// subgraph's HttpClient by that name; without it the gateway cannot reach the subgraph at all.
builder.Services.AddHttpClient("Subgraph");

// Nitro runs in a browser, so it sends an Origin header and a CORS preflight. Without this the
// browser blocks the response and Nitro reports the endpoint as unreachable even though the
// server answered — the same request from a shell client succeeds, which makes it confusing.
builder.Services.AddCors();

builder.Services
       .AddFusionGatewayServer()
       .ConfigureFromFile(System.IO.Path.Combine(AppContext.BaseDirectory, "gateway.fgp"))
       .CoreBuilder
       // Without this the gateway reports "Unknown subscription error" and swallows the cause,
       // which is exactly what made the production incident hard to diagnose.
       .ModifyRequestOptions(o => o.IncludeExceptionDetails = true);

var app = builder.Build();

// Required for Nitro (or any graphql-ws client) to subscribe over a WebSocket. The short
// keep-alive makes the point of the repro visible quickly: these pings are generated here, by a
// healthy gateway, and keep arriving long after the subgraph behind it has stopped responding.
app.UseCors(c => c.AllowAnyHeader().AllowAnyMethod().AllowAnyOrigin());

app.UseWebSockets(new WebSocketOptions { KeepAliveInterval = TimeSpan.FromSeconds(15) });

// One path serves HTTP, the WebSocket endpoint, the SDL and the IDE. Splitting them dropped
// /graphql/schema.graphql, which is what Nitro fetches to resolve the schema.
app.MapGraphQL("/graphql");
app.Run();
