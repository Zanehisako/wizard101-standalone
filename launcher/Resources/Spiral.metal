#include <metal_stdlib>
using namespace metal;
struct Vertex { float4 position [[position]]; float2 uv; };
vertex Vertex spiralVertex(uint id [[vertex_id]]) {
    float2 p = float2((id << 1) & 2, id & 2);
    return {float4(p * 2.0 - 1.0, 0.0, 1.0), float2(p.x, 1.0 - p.y)};
}
float hash(float2 p) { return fract(sin(dot(p, float2(127.1, 311.7))) * 43758.5453); }
float line(float value, float width) { return 1.0 - smoothstep(width, width * 2.0, abs(value)); }
fragment float4 spiralFragment(Vertex in [[stage_in]], constant float2 &size [[buffer(0)]]) {
    float2 uv = in.uv;
    float2 p = (uv - float2(0.735, 0.43)) * float2(size.x / size.y, 1.0);
    float r = length(p);
    float a = atan2(p.y, p.x);
    float3 col = mix(float3(0.020, 0.030, 0.070), float3(0.055, 0.045, 0.120), uv.x);
    col += float3(0.095, 0.035, 0.160) * exp(-r * r * 7.0);
    col += float3(0.015, 0.050, 0.100) * exp(-length(p - float2(0.1, 0.15)) * 4.0);
    float2 grid = uv * float2(180.0, 120.0);
    float2 cell = floor(grid);
    float2 point = fract(grid) - float2(hash(cell), hash(cell + 27.0));
    float stars = (1.0 - smoothstep(0.02, 0.12, length(point))) * step(0.98, hash(cell + 11.0));
    col += stars * float3(0.6, 0.68, 0.95) * smoothstep(0.28, 0.62, uv.x);
    float circle = line(r - 0.225, 0.0009) + line(r - 0.241, 0.0006);
    float dash = pow(max(0.0, cos(a * 24.0)), 16.0) * line(r - 0.25, 0.004);
    float inner = line(r - 0.179, 0.0006) * 0.5;
    float rays = pow(max(0.0, cos(a * 8.0)), 26.0) * smoothstep(0.185, 0.210, r) * (1.0 - smoothstep(0.215, 0.224, r));
    col += float3(0.63, 0.44, 0.20) * (circle * 0.65 + dash * 0.45 + inner + rays);
    // A faceted crystal inside the astronomical ring.
    float crystal = abs(p.x) / 0.095 + abs(p.y) / 0.153;
    float border = line(crystal - 1.0, 0.012);
    float facet = step(crystal, 1.0) * (0.08 + 0.12 * step(p.x, 0.0) + 0.16 * step(p.y, 0.0));
    col += float3(0.27, 0.45, 0.92) * facet;
    col += float3(0.45, 0.63, 1.0) * border;
    col += float3(0.15, 0.24, 0.55) * exp(-r * r * 80.0);
    // Quiet silhouette at the foot of the scene.
    float ridge = 0.80 + 0.020 * sin(uv.x * 19.0) + 0.017 * cos(uv.x * 37.0);
    col = mix(col, float3(0.016, 0.022, 0.046), smoothstep(ridge, ridge + 0.002, uv.y));
    col *= 0.85 + 0.15 * (1.0 - length(uv - 0.5));
    return float4(col, 1.0);
}
