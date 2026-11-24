using System.Buffers.Binary;
using System.Text;
using LlamaLogic.Packages;

if (args.Length != 4)
    throw new ArgumentException("Usage: build-package <interaction.xml> <snippet.xml> <output.package> <display-name>");

const ulong interactionId = 11368423882965899103UL;
const ulong snippetId = 14966811642716490557UL;
const uint displayKey = 0xEFF39C5F;
const string displayText = "Se Preparar para a Aula";

var package = new DataBasePackedFile();
package.SetXml(new ResourceKey(ResourceType.InteractionTuning, 0, interactionId), File.ReadAllText(args[0]));
package.SetXml(new ResourceKey(ResourceType.SnippetTuning, 0, snippetId), File.ReadAllText(args[1]));
package.Set(
    new ResourceKey(ResourceType.StringTable, 0, 0),
    new ReadOnlyMemory<byte>(BuildStbl(displayKey, displayText)));
package.SaveAs(args[2]);

using var verify = new DataBasePackedFile(args[2]);
if (verify.Count != 3)
    throw new InvalidDataException($"Expected 3 package resources; found {verify.Count}.");
if (!verify.ContainsKey(new ResourceKey(ResourceType.InteractionTuning, 0, interactionId)))
    throw new InvalidDataException("Interaction tuning missing from package.");
if (!verify.ContainsKey(new ResourceKey(ResourceType.SnippetTuning, 0, snippetId)))
    throw new InvalidDataException("XML Injector snippet missing from package.");
if (!verify.ContainsKey(new ResourceKey(ResourceType.StringTable, 0, 0)))
    throw new InvalidDataException("String table missing from package.");

Console.WriteLine($"Validated DBPF package with {verify.Count} resources: {args[2]}");

static byte[] BuildStbl(uint key, string value)
{
    var text = Encoding.UTF8.GetBytes(value);
    if (text.Length > ushort.MaxValue)
        throw new ArgumentOutOfRangeException(nameof(value));
    using var stream = new MemoryStream();
    using var writer = new BinaryWriter(stream, Encoding.UTF8, leaveOpen: true);
    writer.Write(Encoding.ASCII.GetBytes("STBL"));
    writer.Write((ushort)5);
    writer.Write((byte)0);
    writer.Write((ulong)1);
    writer.Write((ushort)0);
    writer.Write((uint)text.Length);
    writer.Write(key);
    writer.Write((byte)0);
    writer.Write((ushort)text.Length);
    writer.Write(text);
    writer.Flush();
    return stream.ToArray();
}