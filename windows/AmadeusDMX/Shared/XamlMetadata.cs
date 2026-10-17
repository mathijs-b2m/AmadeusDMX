// WinUI reads its own themes (themeresources.xaml) through the app's XAML type information, which the XAML
// compiler generates for an app with XAML files. Ours has none, so App hands WinUI's own provider on: without it
// XamlControlsResources fails at start ("Cannot find a resource with the given key: AcrylicBackground…").
using Microsoft.UI.Xaml.Markup;
using Microsoft.UI.Xaml.XamlTypeInfo;

namespace AmadeusDMX;

public sealed partial class App : IXamlMetadataProvider
{
    readonly XamlControlsXamlMetaDataProvider _xamlTypes = new();

    public IXamlType GetXamlType(Type type) => _xamlTypes.GetXamlType(type);
    public IXamlType GetXamlType(string fullName) => _xamlTypes.GetXamlType(fullName);
    public XmlnsDefinition[] GetXmlnsDefinitions() => _xamlTypes.GetXmlnsDefinitions();
}
