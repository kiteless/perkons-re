// Prepare a raw Perkons segment for analysis: STM32H7 memory map, Thumb mode,
// vector table, and names from symbols/<version>-<core>.json.
// Run as a -preScript on a BinaryLoader import. Script arg: path to the symbols JSON.
// @category Perkons
import com.google.gson.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.*;
import java.io.FileReader;
import java.math.BigInteger;
import java.util.Map;

public class PerkonsSetup extends GhidraScript {
    // name, start, size, volatile (peripheral)
    static final Object[][] REGIONS = {
        {"ITCM", 0x00000000L, 0x10000L, false},
        {"D2_SRAM_ALIAS", 0x10000000L, 0x48000L, false},
        {"DTCM", 0x20000000L, 0x20000L, false},
        {"AXI_SRAM", 0x24000000L, 0x80000L, false},
        {"D2_SRAM", 0x30000000L, 0x48000L, false},
        {"D3_SRAM", 0x38000000L, 0x10000L, false},
        {"BACKUP_SRAM", 0x38800000L, 0x1000L, false},
        {"APB1", 0x40000000L, 0x10000L, true},
        {"APB2", 0x40010000L, 0x10000L, true},
        {"AHB1", 0x40020000L, 0x60000L, true},
        {"AHB2", 0x48020000L, 0x4000L, true},
        {"APB3", 0x50000000L, 0x10000L, true},
        {"AHB3", 0x51000000L, 0x2000000L, true},
        {"APB4_AHB4", 0x58000000L, 0x30000L, true},
        {"SCS", 0xE0000000L, 0x100000L, true},
    };

    long hex(JsonObject o, String k) {
        return Long.decode(o.get(k).getAsString());
    }

    Address a(long v) {
        return toAddr(v);
    }

    void block(String name, long start, long size, boolean vol) throws Exception {
        MemoryBlock b = currentProgram.getMemory().createUninitializedBlock(name, a(start), size, false);
        b.setRead(true);
        b.setWrite(true);
        b.setExecute(!vol);
        b.setVolatile(vol);
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            printerr("usage: PerkonsSetup.java <symbols.json>");
            return;
        }
        JsonObject sym = JsonParser.parseReader(new FileReader(args[0])).getAsJsonObject();
        Memory mem = currentProgram.getMemory();
        long base = hex(sym, "segment_base");
        Address flashStart = a(base);
        MemoryBlock flash = mem.getBlock(flashStart);
        flash.setName("FLASH");
        flash.setWrite(false);
        flash.setExecute(true);

        // .data initial values (copied from flash by the reset handler), so pointers and
        // strings stored in initialized globals resolve during analysis
        long ds = 0, de = 0;
        byte[] init = null;
        if (sym.has("memory")) {
            JsonObject m = sym.getAsJsonObject("memory");
            ds = hex(m, "data_start");
            de = hex(m, "data_end");
            init = new byte[(int) (de - ds)];
            mem.getBytes(a(hex(m, "data_lma")), init);
        }

        // RAM / peripheral blocks; the one holding .data is split into before/.data/after
        for (Object[] r : REGIONS) {
            String name = (String) r[0];
            long rs = (Long) r[1], re = rs + (Long) r[2];
            boolean vol = (Boolean) r[3];
            if (mem.getBlock(a(rs)) != null) continue;
            if (init != null && ds >= rs && de <= re) {
                if (ds > rs) block(name, rs, ds - rs, vol);
                MemoryBlock b = mem.createInitializedBlock(name + "_data", a(ds),
                    new java.io.ByteArrayInputStream(init), init.length, monitor, false);
                b.setRead(true);
                b.setWrite(true);
                if (re > de) block(name + "_bss", de, re - de, vol);
            } else {
                block(name, rs, re - rs, vol);
            }
        }
        if (sym.has("memory")) {
            JsonObject m = sym.getAsJsonObject("memory");
            createLabel(a(ds), "_sdata", true);
            createLabel(a(hex(m, "bss_start")), "_sbss", true);
            createLabel(a(hex(m, "bss_end")), "_ebss", true);
        }

        // All code is Thumb: set TMode=1 over the flash image
        Register tmode = currentProgram.getProgramContext().getRegister("TMode");
        currentProgram.getProgramContext().setValue(tmode, flash.getStart(), flash.getEnd(), BigInteger.ONE);

        // Vector table: 16 core exceptions + IRQs, stop at the first non-code word
        String[] core = {"_estack", "Reset_Handler", "NMI_Handler", "HardFault_Handler", "MemManage_Handler",
            "BusFault_Handler", "UsageFault_Handler", null, null, null, null, "SVC_Handler", "DebugMon_Handler",
            null, "PendSV_Handler", "SysTick_Handler"};
        for (int i = 0; i < 16 + 150; i++) {
            Address slot = flashStart.add(4L * i);
            long v = mem.getInt(slot) & 0xFFFFFFFFL;
            createDWord(slot);
            if (i == 0) {
                createLabel(slot, "vector_estack", true);
                continue;
            }
            if (v == 0) continue;
            if ((v & 1) == 0 || !flash.contains(a(v & ~1L))) break;
            String name = i < 16 ? core[i] : String.format("IRQ%d_Handler", i - 16);
            if (name == null) name = String.format("exc%d_Handler", i);
            Address fn = a(v & ~1L);
            if (getFunctionAt(fn) == null) {
                disassemble(fn);
                createFunction(fn, null);
            }
            // shared default handlers get a generic name; don't overwrite a better one
            Symbol s = getSymbolAt(fn);
            if (s == null || s.getSource() == SourceType.DEFAULT) createLabel(fn, name, true);
            createLabel(slot, "vec_" + name, false);
        }

        // Named functions and globals from the symbols file
        if (sym.has("functions")) {
            for (Map.Entry<String, JsonElement> e : sym.getAsJsonObject("functions").entrySet()) {
                if (e.getKey().startsWith("_")) continue;
                Address fn = a(Long.decode(e.getValue().getAsString()) & ~1L);
                disassemble(fn);
                Function f = getFunctionAt(fn);
                if (f == null) f = createFunction(fn, e.getKey());
                else f.setName(e.getKey(), SourceType.USER_DEFINED);
            }
        }
        if (sym.has("globals")) {
            for (Map.Entry<String, JsonElement> e : sym.getAsJsonObject("globals").entrySet()) {
                if (e.getKey().startsWith("_")) continue;
                createLabel(a(Long.decode(e.getValue().getAsString())), e.getKey(), true);
            }
        }
        println("PerkonsSetup: done for " + args[0]);
    }
}
