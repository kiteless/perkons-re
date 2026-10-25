// Find what references something and decompile those functions.
// Script args: <outdir> <query> [<query> ...]   each query is one of
//   addr:0x38000000       functions referencing this address (directly or via literal pool)
//   str:<regex>           functions referencing defined strings matching regex
//   callers:<name|0xaddr> functions calling this function
//   fn:<name|0xaddr>      just this function
// Writes <outdir>/<addr>_<name>.c for every hit plus <outdir>/query.txt (what hit why).
// @category Perkons
import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.data.StringDataInstance;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.util.DefinedDataIterator;
import java.io.*;
import java.util.*;
import java.util.regex.Pattern;

public class Query extends GhidraScript {
    PrintWriter log;
    Map<Function, Set<String>> hits = new TreeMap<>(Comparator.comparing(Function::getEntryPoint));

    void hit(Function f, String why) {
        if (f == null) return;
        hits.computeIfAbsent(f, k -> new LinkedHashSet<>()).add(why);
    }

    // references to `target`, following one level of literal-pool indirection
    void refsTo(Address target, String why) {
        for (Reference r : getReferencesTo(target)) {
            Address from = r.getFromAddress();
            Function f = getFunctionContaining(from);
            if (f != null) {
                hit(f, why + " @" + from);
                continue;
            }
            for (Reference r2 : getReferencesTo(from)) hit(getFunctionContaining(r2.getFromAddress()), why + " via pool " + from);
        }
        // pools Ghidra didn't turn into references: scan for the raw word
        byte[] pat = new byte[4];
        long v = target.getOffset();
        for (int i = 0; i < 4; i++) pat[i] = (byte) (v >> (8 * i));
        Address a = currentProgram.getMinAddress();
        while (a != null) {
            a = find(a, pat);
            if (a == null) break;
            if (a.getOffset() % 2 == 0 && getFunctionContaining(a) == null) {
                for (Reference r2 : getReferencesTo(a)) hit(getFunctionContaining(r2.getFromAddress()), why + " via word " + a);
            }
            a = a.add(1);
        }
    }

    Function fnByNameOrAddr(String s) {
        if (s.startsWith("0x")) return getFunctionContaining(toAddr(Long.decode(s) & ~1L));
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) if (f.getName().equals(s)) return f;
        return null;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File out = new File(args[0]);
        out.mkdirs();
        log = new PrintWriter(new File(out, "query.txt"));
        for (int i = 1; i < args.length; i++) {
            String q = args[i];
            if (q.startsWith("addr:")) {
                refsTo(toAddr(Long.decode(q.substring(5))), q);
            } else if (q.startsWith("str:")) {
                Pattern p = Pattern.compile(q.substring(4));
                for (Data d : DefinedDataIterator.byDataInstance(currentProgram, StringDataInstance::isString)) {
                    String s = StringDataInstance.getStringDataInstance(d).getStringValue();
                    if (s != null && p.matcher(s).find()) {
                        log.println("string " + d.getAddress() + " \"" + s + "\"");
                        refsTo(d.getAddress(), "str \"" + s + "\"");
                    }
                }
            } else if (q.startsWith("callers:")) {
                Function t = fnByNameOrAddr(q.substring(8));
                if (t != null) for (Function c : t.getCallingFunctions(monitor)) hit(c, q);
            } else if (q.startsWith("fn:")) {
                hit(fnByNameOrAddr(q.substring(3)), q);
            }
        }
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        for (Map.Entry<Function, Set<String>> e : hits.entrySet()) {
            Function f = e.getKey();
            String name = String.format("%08x_%s.c", f.getEntryPoint().getOffset(), f.getName());
            log.println(name + "  <- " + String.join("; ", e.getValue()));
            DecompileResults r = d.decompileFunction(f, 60, monitor);
            try (PrintWriter w = new PrintWriter(new File(out, name))) {
                w.println("// " + String.join("\n// ", e.getValue()));
                w.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "// failed: " + r.getErrorMessage());
            }
        }
        log.close();
        println("Query: " + hits.size() + " functions -> " + out);
    }
}
