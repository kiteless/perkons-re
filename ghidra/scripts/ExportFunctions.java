// Export every function (entry + body ranges) as JSON for tools/port_symbols.py.
// Script arg: <out.json>
// @category Perkons
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.io.PrintWriter;

public class ExportFunctions extends GhidraScript {
    @Override
    public void run() throws Exception {
        try (PrintWriter w = new PrintWriter(getScriptArgs()[0])) {
            w.println("{");
            boolean first = true;
            for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
                StringBuilder b = new StringBuilder();
                for (AddressRange r : f.getBody()) {
                    if (b.length() > 0) b.append(",");
                    b.append(String.format("[%d,%d]", r.getMinAddress().getOffset(), r.getMaxAddress().getOffset() + 1));
                }
                w.print((first ? "" : ",\n") + String.format("\"%d\": {\"name\": \"%s\", \"body\": [%s]}",
                    f.getEntryPoint().getOffset(), f.getName(), b));
                first = false;
            }
            w.println("\n}");
        }
        println("ExportFunctions: done");
    }
}
