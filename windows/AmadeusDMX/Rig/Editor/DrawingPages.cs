// The drawings under a rig: each one's page (a one-page PDF from the engine) rendered to a picture with Windows's
// own PDF renderer (Windows.Data.Pdf; the Mac uses PDFKit), about 2048 px on its long side, once per file: a page's
// file name is its content's hash, so a picture never goes stale.
using System.Runtime.InteropServices.WindowsRuntime;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Data.Pdf;
using Windows.Graphics.Imaging;
using Windows.Storage.Streams;

namespace AmadeusDMX;

public static class DrawingPages
{
    public const int LongSide = 2048;

    static readonly Dictionary<string, Task<DrawingPicture?>> Cache = [];

    /// The page of `file` as a picture (from the engine, rendered here), or nil when it can't be had.
    public static Task<DrawingPicture?> Picture(SetupAPI api, string file)
    {
        if (Cache.TryGetValue(file, out var t) && !(t.IsCompleted && t.Result is null)) return t;  // a failed one is tried again
        return Cache[file] = Load(api, file);
    }

    static async Task<DrawingPicture?> Load(SetupAPI api, string file)
    {
        try { return await Render(await api.UnderlayPage(file)); }
        catch (Exception e) when (e is not OutOfMemoryException) { return null; }
    }

    /// The first page of a PDF as BGRA pixels (premultiplied, on white), `LongSide` px on its long side.
    public static async Task<DrawingPicture?> Render(byte[] pdf)
    {
        using var input = new InMemoryRandomAccessStream();
        await input.WriteAsync(pdf.AsBuffer());
        input.Seek(0);
        var doc = await PdfDocument.LoadFromStreamAsync(input);
        if (doc.PageCount == 0) return null;
        using var page = doc.GetPage(0);
        var size = page.Size;
        if (size.Width <= 0 || size.Height <= 0) return null;
        var k = LongSide / Math.Max(size.Width, size.Height);
        var options = new PdfPageRenderOptions
        {
            DestinationWidth = (uint)Math.Max(1, Math.Round(size.Width * k)), DestinationHeight = (uint)Math.Max(1, Math.Round(size.Height * k)),
            BackgroundColor = Microsoft.UI.Colors.White,
        };
        using var png = new InMemoryRandomAccessStream();
        await page.RenderToStreamAsync(png, options);
        png.Seek(0);
        var decoder = await BitmapDecoder.CreateAsync(png);
        var pixels = await decoder.GetPixelDataAsync(BitmapPixelFormat.Bgra8, BitmapAlphaMode.Premultiplied, new BitmapTransform(),
            ExifOrientationMode.IgnoreExifOrientation, ColorManagementMode.DoNotColorManage);
        return new DrawingPicture((int)decoder.PixelWidth, (int)decoder.PixelHeight, pixels.DetachPixelData());
    }

    /// The picture for an Image (the Line Up sheet).
    public static WriteableBitmap Bitmap(DrawingPicture p)
    {
        var b = new WriteableBitmap(p.Width, p.Height);
        using (var s = b.PixelBuffer.AsStream()) s.Write(p.Bgra, 0, Math.Min(p.Bgra.Length, (int)b.PixelBuffer.Capacity));
        b.Invalidate();
        return b;
    }
}
