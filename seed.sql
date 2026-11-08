-- Kurikulum pemula (6 topik). Jalankan setelah schema.sql:
-- psql -d ai_english_tutor -f seed.sql

INSERT INTO curriculum_topics (level, urutan, judul, tujuan, contoh_kalimat) VALUES
('pemula', 1, 'Perkenalan diri',
 'Menyebut nama, asal, umur, dan status sebagai mahasiswa dengan to be (am/is/are).',
 'Hi, my name is Rina. I am from Bandung. I am a first-year student.'),
('pemula', 2, 'Kampus & jurusan',
 'Menjelaskan nama kampus, jurusan, dan alasan memilih jurusan dengan simple present.',
 'I study Informatics at Universitas Indonesia. I like it because I enjoy coding.'),
('pemula', 3, 'Rutinitas harian',
 'Menceritakan kegiatan sehari-hari dengan simple present dan keterangan waktu (always, usually, at 7 a.m.).',
 'I usually wake up at 5 a.m. Then I take a shower and go to campus by motorcycle.'),
('pemula', 4, 'Hobi',
 'Membicarakan hobi dan frekuensinya dengan like/enjoy + verb-ing.',
 'I like playing badminton. I play it every Sunday with my friends.'),
('pemula', 5, 'Arah & tempat',
 'Bertanya dan menjelaskan lokasi dengan preposisi tempat dan kalimat perintah sederhana.',
 'Excuse me, where is the library? Go straight and turn left. It is next to the canteen.'),
('pemula', 6, 'Minta tolong',
 'Meminta bantuan dengan sopan memakai can/could you dan menanggapi permintaan.',
 'Could you help me, please? Can you lend me your pen? Sure, here you are.')
ON CONFLICT (level, urutan) DO NOTHING;
