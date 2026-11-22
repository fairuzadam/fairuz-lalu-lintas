# Tugas Project Individu: Simulator Lampu Lalu Lintas + HMI

Isi folder:

| File | Fungsi |
|---|---|
| `server.py` | "Otak PLC" (timer fase, interlock) + web server. Port 3000 = simulator, port 3001 = HMI |
| `simulator.html` | Tampilan persimpangan 4 arah (mobil + lampu) |
| `hmi.html` | Panel kontrol: START/STOP, AUTO/MANUAL, DARURAT, atur timer, tabel I/O |

Alur sesuai papan tulis:

```
Domain  ->  Cloudflare  ->  tunneling  ->  server (Python)
                                           |- localhost:3000  simulator.html
                                           `- localhost:3001  hmi.html
```

---

## 1. Coba di laptop dulu

```bash
python3 server.py
```

Buka `http://localhost:3000` (simulator) dan `http://localhost:3001` (HMI) di dua tab.
Tekan tombol di HMI, simulatornya langsung ikut berubah.

## 2. Bikin domain

1. Beli domain `.my.id` (murah, biasanya belasan ribu per tahun) di registrar seperti Niagahoster, Rumahweb, Domainesia, dll. Contoh: `namakalian.my.id`.
2. Atau `.com` kalau mau, bedanya cuma harga.

## 3. Cloudflare + GitHub

**Cloudflare**
1. Daftar di cloudflare.com, klik **Add a site**, masukin domain lo, pilih plan **Free**.
2. Cloudflare ngasih 2 nameserver. Ganti nameserver domain lo ke situ lewat panel registrar.
3. Tunggu status domain jadi **Active** (bisa beberapa menit sampai beberapa jam).

**GitHub**
```bash
git init
git add .
git commit -m "simulator lampu lalu lintas"
git branch -M main
git remote add origin https://github.com/USERNAME/lalu-lintas.git
git push -u origin main
```

## 4. Linux server (Termux / SSH terminal)

Di Termux (HP) atau Linux server lewat SSH:

```bash
pkg install python git cloudflared      # Termux
# Ubuntu/Debian: sudo apt install python3 git  (cloudflared lihat docs Cloudflare)

git clone https://github.com/USERNAME/lalu-lintas.git
cd lalu-lintas
python3 server.py
```

## 5. Tunneling Cloudflare

Tunnel bikin server lo bisa diakses publik tanpa buka port router.

```bash
cloudflared tunnel login
cloudflared tunnel create lalulintas
cloudflared tunnel route dns lalulintas simulator.namakalian.my.id
cloudflared tunnel route dns lalulintas hmi.namakalian.my.id
```

Bikin file `~/.cloudflared/config.yml`:

```yaml
tunnel: lalulintas
credentials-file: /home/USER/.cloudflared/<ID-TUNNEL>.json

ingress:
  - hostname: simulator.namakalian.my.id
    service: http://localhost:3000
  - hostname: hmi.namakalian.my.id
    service: http://localhost:3001
  - service: http_status:404
```

Jalankan (terminal 1 `python3 server.py`, terminal 2):

```bash
cloudflared tunnel run lalulintas
```

Hasil akhir:
- `https://simulator.namakalian.my.id` -> simulator
- `https://hmi.namakalian.my.id` -> HMI

Alternatif yang lebih gampang: di dashboard Cloudflare **Zero Trust > Networks > Tunnels**, bikin tunnel, copy token, lalu `cloudflared tunnel run --token <TOKEN>`. Hostname dan service (`localhost:3000` / `3001`) diisi lewat web.

---

## 6. Logika PLC (buat dijelasin ke dosen)

**Pemetaan I/O**

| Alamat | Fungsi |
|---|---|
| X0 | START |
| X1 | STOP |
| X2 | DARURAT |
| X3 | MANUAL |
| Y0 / Y1 / Y2 | Utara-Selatan merah / kuning / hijau |
| Y3 / Y4 / Y5 | Timur-Barat merah / kuning / hijau |

**Urutan fase otomatis** (default, bisa diubah di HMI):

| Fase | Y aktif | Durasi |
|---|---|---|
| 1 | Y2 + Y3 (U-S hijau, T-B merah) | 10 s |
| 2 | Y1 + Y3 (U-S kuning) | 3 s |
| 3 | Y0 + Y3 (semua merah) | 1 s |
| 4 | Y0 + Y5 (T-B hijau, U-S merah) | 10 s |
| 5 | Y0 + Y4 (T-B kuning) | 3 s |
| 6 | Y0 + Y3 (semua merah) | 1 s |

Lalu balik ke fase 1.

**Versi ladder (gaya Mitsubishi GX Works)**

Timer 100 ms: K100 = 10 detik, K30 = 3 detik, K10 = 1 detik. Timer berantai: tiap timer
mulai setelah timer sebelumnya selesai, jadi totalnya satu siklus penuh.

```
Rung 1  Self-holding RUN
  X0 ----+---/X1----( M0 )        M0 = sistem jalan (START nyala, STOP putus)
  M0 ----+

Rung 2  Timer berantai
  M0 --/T5--------------( T0 K100 )     fase 1  U-S hijau
  T0 --------------------( T1 K30  )    fase 2  U-S kuning
  T1 --------------------( T2 K10  )    fase 3  semua merah
  T2 --------------------( T3 K100 )    fase 4  T-B hijau
  T3 --------------------( T4 K30  )    fase 5  T-B kuning
  T4 --------------------( T5 K10  )    fase 6  semua merah, T5 selesai = ulang ke T0

Rung 3  Penanda fase (M10..M15)
  M10 (fase 1) = M0 . /T0
  M11 (fase 2) = T0 . /T1
  M12 (fase 3) = T1 . /T2
  M13 (fase 4) = T2 . /T3
  M14 (fase 5) = T3 . /T4
  M15 (fase 6) = T4 . /T5

Rung 4  Output lampu (aktif kalau tidak darurat: /X2)
  Y2 = M10                          U-S hijau
  Y1 = M11                          U-S kuning
  Y0 = M12 + M13 + M14 + M15        U-S merah
  Y3 = M10 + M11 + M12 + M15        T-B merah
  Y5 = M13                          T-B hijau
  Y4 = M14                          T-B kuning

Rung 5  Darurat (X2): Y1 dan Y4 kedip pakai SM412 (clock 1 detik), output lain OFF
Rung 6  Interlock: Y2 dan Y5 tidak boleh ON bersamaan (kontak NC saling silang)
```

Catatan: ladder di atas cuma gambaran logika, sesuaikan sama format yang dosen minta
kalau harus dibuat di GX Works. Di `server.py` logika yang sama jalan di fungsi
`scan_loop()` (timer) dan `outputs()` (Y0..Y5).

## 7. Fitur yang bisa lo tunjukin pas demo

1. Mode AUTO: lampu jalan sendiri, mobil berhenti saat merah.
2. Ubah timer hijau jadi 5 detik lewat HMI, lihat efeknya.
3. STOP: semua merah. START: lanjut lagi.
4. DARURAT: semua kedip kuning, mobil jalan pelan.
5. MANUAL: coba pindah U-S hijau langsung ke T-B hijau, ditolak interlock (harus lewat semua merah).
6. Buka dari HP lewat URL domain (bukti tunneling jalan).
