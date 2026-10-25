// Write decompiled C for functions to <outdir>/<addr>_<name>.c
// Script args: <outdir> <addr-or-name> [...]   ("all" = every function)
// @category Perkons
import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import java.io.*;
import java.util.*;

public class Decompile extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File out = new File(args[0]);
        out.mkdirs();
        List<Function> fns = new ArrayList<>();
        for (int i = 1; i < args.length; i++) {
            if (args[i].equals("all")) {
                currentProgram.getFunctionManager().getFunctions(true).forEach(fns::add);
            } else if (args[i].startsWith("0x")) {
                Function f = getFunctionContaining(toAddr(Long.decode(args[i]) & ~1L));
                if (f != null) fns.add(f);
                else printerr("no function at " + args[i]);
            } else {
                for (Function f : currentProgram.getFunctionManager().getFunctions(true))
                    if (f.getName().equals(args[i])) fns.add(f);
            }
        }
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        for (Function f : fns) {
            DecompileResults r = d.decompileFunction(f, 60, monitor);
            String name = String.format("%08x_%s.c", f.getEntryPoint().getOffset(), f.getName());
            try (PrintWriter w = new PrintWriter(new File(out, name))) {
                w.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "// failed: " + r.getErrorMessage());
            }
        }
        println("Decompile: wrote " + fns.size() + " functions to " + out);
    }
}
