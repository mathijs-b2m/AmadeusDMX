// Buffer layouts shared with the shaders (Shaders.swift): keep both in step.
import simd

struct Uniforms {
    var viewProj: simd_float4x4
    var camPos: SIMD4<Float>
    var camRight: SIMD4<Float>
    var camUp: SIMD4<Float>
    var params: SIMD4<Float>    // time, haze, exposure, bounce
    var ambient: SIMD4<Float>
}

struct BeamInstance { var apexLen: SIMD4<Float>; var dirRadius: SIMD4<Float>; var color: SIMD4<Float>; var extra: SIMD4<Float> }
struct SpriteInstance { var centerSize: SIMD4<Float>; var color: SIMD4<Float>; var extra: SIMD4<Float> }
struct DecalInstance { var centerRadius: SIMD4<Float>; var normal: SIMD4<Float>; var color: SIMD4<Float> }
struct LineInstance { var p0Width: SIMD4<Float>; var p1: SIMD4<Float>; var color: SIMD4<Float> }
struct WallVertex { var pos: SIMD3<Float>; var uv: SIMD2<Float> }
struct WallParams { var info: SIMD4<Float>; var bands: SIMD4<Float>; var pal: (SIMD4<Float>, SIMD4<Float>, SIMD4<Float>, SIMD4<Float>) }
