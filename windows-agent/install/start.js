// Chay Rookie Agent bang Python di kem trong goi, ngay trong cua so nay (khong qua .cmd/PowerShell), loi hien thang ra man hinh.
//   npm start        -> trang quan ly, Python 64-bit        npm run start32 -> Python 32-bit (Java 32-bit cua IE)
//   npm run status   -> chi in ket qua kiem tra may         npm run status32
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const bits = process.argv[2] === "32" ? "32" : "64";
const mode = process.argv[3] === "status" ? "status" : "web";
const python = path.join(__dirname, "runtime", "py" + bits, "python.exe");
if (!fs.existsSync(python)) {
  console.error("Khong thay " + python + ". Hay chay trong thu muc goi da giai nen.");
  process.exit(1);
}
const args = mode === "status" ? ["-m", "rookie_agent", "status"] : ["-m", "rookie_agent", "web", "--start-server"];
console.log("Chay: " + python + " " + args.join(" ") + "\n(Dong cua so nay hoac Ctrl+C de dung.)\n");
const child = spawn(python, args, { cwd: path.join(__dirname, "windows-agent"), stdio: "inherit", env: { ...process.env, PYTHONUTF8: "1" } });
child.on("exit", (code) => process.exit(code ?? 0));
