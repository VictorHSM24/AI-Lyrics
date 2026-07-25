"""Sprint 21.7 — Corpus de referências bíblicas para validação estatística.

100 frases categorizadas + 5 dependentes de contexto.
Ground truth: (livro, capítulo, versículo).
"""

# Categoria, dificuldade, frase, livro, capítulo, versículo
# versículo=0 significa capítulo inteiro
CORPUS = [
    # ===== SALMOS (15) =====
    ("Salmos", "facil", "O Senhor é meu pastor.", "Salmos", 23, 1),
    ("Salmos", "facil", "Ainda que eu ande pelo vale da sombra da morte.", "Salmos", 23, 4),
    ("Salmos", "facil", "O Senhor é a minha luz e a minha salvação.", "Salmos", 27, 1),
    ("Salmos", "facil", "Entrega o teu caminho ao Senhor.", "Salmos", 37, 5),
    ("Salmos", "media", "Alegrei-me quando me disseram vamos à casa do Senhor.", "Salmos", 122, 1),
    ("Salmos", "media", "Deus é o nosso refúgio e fortaleza.", "Salmos", 46, 1),
    ("Salmos", "media", "Cria em mim um coração puro.", "Salmos", 51, 10),
    ("Salmos", "media", "Os céus declaram a glória de Deus.", "Salmos", 19, 1),
    ("Salmos", "dificil", "As misericórdias do Senhor são a causa de não sermos consumidos.", "Lamentações", 3, 22),
    ("Salmos", "dificil", "Quem subirá ao monte do Senhor.", "Salmos", 24, 3),
    ("Salmos", "dificil", "A alegria do Senhor é a vossa força.", "Neemias", 8, 10),
    ("Salmos", "dificil", "Bem-aventurado o homem a quem o Senhor não imputa iniquidade.", "Salmos", 32, 2),
    ("Salmos", "media", "Lâmpada para os meus pés é a tua palavra.", "Salmos", 119, 105),
    ("Salmos", "facil", "Tudo tem o seu tempo determinado.", "Eclesiastes", 3, 1),
    ("Salmos", "media", "Perto está o Senhor dos que têm o coração quebrantado.", "Salmos", 34, 18),

    # ===== EVANGELHOS (20) =====
    ("Evangelhos", "facil", "Porque Deus amou o mundo de tal maneira.", "João", 3, 16),
    ("Evangelhos", "facil", "Buscai primeiro o Reino de Deus.", "Mateus", 6, 33),
    ("Evangelhos", "facil", "Vinde a mim todos os que estais cansados.", "Mateus", 11, 28),
    ("Evangelhos", "facil", "Eu sou o caminho a verdade e a vida.", "João", 14, 6),
    ("Evangelhos", "facil", "A paz eu vos deixo a minha paz vos dou.", "João", 14, 27),
    ("Evangelhos", "facil", "Bem-aventurados os pobres de espírito.", "Mateus", 5, 3),
    ("Evangelhos", "facil", "Bem-aventurados os que choram.", "Mateus", 5, 4),
    ("Evangelhos", "facil", "Bem-aventurados os mansos.", "Mateus", 5, 5),
    ("Evangelhos", "media", "Ninguém pode servir a dois senhores.", "Mateus", 6, 24),
    ("Evangelhos", "media", "Pedra sobre a qual edificarei a minha igreja.", "Mateus", 16, 18),
    ("Evangelhos", "media", "As raposas têm covis e as aves do céu têm ninhos.", "Mateus", 8, 20),
    ("Evangelhos", "media", "A seara é grande mas os trabalhadores são poucos.", "Mateus", 9, 37),
    ("Evangelhos", "media", "Quem quiser vir após mim tome a sua cruz.", "Marcos", 8, 34),
    ("Evangelhos", "dificil", "Nem todo o que me diz Senhor Senhor entrará no Reino dos céus.", "Mateus", 7, 21),
    ("Evangelhos", "dificil", "Muitos são chamados mas poucos escolhidos.", "Mateus", 22, 14),
    ("Evangelhos", "dificil", "A quem muito foi dado muito será exigido.", "Lucas", 12, 48),
    ("Evangelhos", "dificil", "O espírito é o que vivifica a carne para nada aproveita.", "João", 6, 63),
    ("Evangelhos", "media", "Eu sou a videira vós sois os ramos.", "João", 15, 5),
    ("Evangelhos", "media", "No mundo tereis aflições mas tende bom ânimo.", "João", 16, 33),
    ("Evangelhos", "dificil", "Conhecereis a verdade e a verdade vos libertará.", "João", 8, 32),

    # ===== CARTAS PAULINAS (20) =====
    ("Cartas", "facil", "Tudo posso naquele que me fortalece.", "Filipenses", 4, 13),
    ("Cartas", "facil", "O justo viverá pela fé.", "Romanos", 1, 17),
    ("Cartas", "facil", "Porque pela graça sois salvos mediante a fé.", "Efésios", 2, 8),
    ("Cartas", "facil", "A armadura de Deus.", "Efésios", 6, 11),
    ("Cartas", "facil", "Revesti-vos do novo homem.", "Efésios", 4, 24),
    ("Cartas", "facil", "O amor de Cristo nos constrange.", "2 Coríntios", 5, 14),
    ("Cartas", "media", "Não vos conformeis com este mundo.", "Romanos", 12, 2),
    ("Cartas", "media", "Toda a Escritura é divinamente inspirada.", "2 Timóteo", 3, 16),
    ("Cartas", "media", "Porque para mim o viver é Cristo.", "Filipenses", 1, 21),
    ("Cartas", "media", "A minha graça te basta.", "2 Coríntios", 12, 9),
    ("Cartas", "media", "Sede imitadores de Deus como filhos amados.", "Efésios", 5, 1),
    ("Cartas", "media", "Regozijai-vos sempre no Senhor.", "Filipenses", 4, 4),
    ("Cartas", "dificil", "Não por força nem por violência mas pelo meu Espírito.", "Zacarias", 4, 6),
    ("Cartas", "dificil", "Porque as coisas que se vêem são temporais.", "2 Coríntios", 4, 18),
    ("Cartas", "dificil", "Sujeai-vos uns aos outros no temor de Cristo.", "Efésios", 5, 21),
    ("Cartas", "dificil", "Porque não recebestes o espírito de escravidão.", "Romanos", 8, 15),
    ("Cartas", "dificil", "A fé é o firme fundamento das coisas que se esperam.", "Hebreus", 11, 1),
    ("Cartas", "media", "Deixando toda a malícia e todo o engano.", "1 Pedro", 2, 1),
    ("Cartas", "media", "Sede sóbrios e vigilantes.", "1 Pedro", 5, 8),
    ("Cartas", "facil", "Sede transformados pela renovação do vosso entendimento.", "Romanos", 12, 2),

    # ===== PENTATEUCO (10) =====
    ("Pentateuco", "facil", "No princípio criou Deus os céus e a terra.", "Gênesis", 1, 1),
    ("Pentateuco", "facil", "Ama o teu próximo como a ti mesmo.", "Levítico", 19, 18),
    ("Pentateuco", "media", "Eu sou o que sou.", "Êxodo", 3, 14),
    ("Pentateuco", "media", "Não terás outros deuses diante de mim.", "Êxodo", 20, 3),
    ("Pentateuco", "media", "Honra teu pai e tua mãe.", "Êxodo", 20, 12),
    ("Pentateuco", "media", "Não matarás.", "Êxodo", 20, 13),
    ("Pentateuco", "dificil", "O Senhor pelejará por vós e vós vos calareis.", "Êxodo", 14, 14),
    ("Pentateuco", "dificil", "Vós sereis para mim reino sacerdotal e povo santo.", "Êxodo", 19, 6),
    ("Pentateuco", "dificil", "Vê agora que eu sou e não há outro Deus além de mim.", "Deuteronômio", 32, 39),
    ("Pentateuco", "media", "Ouve Israel o Senhor nosso Deus é o único Senhor.", "Deuteronômio", 6, 4),

    # ===== PROFETAS (10) =====
    ("Profetas", "facil", "Eis que a virgem conceberá e dará à luz um filho.", "Isaías", 7, 14),
    ("Profetas", "facil", "Porque um menino nos nasceu um filho se nos deu.", "Isaías", 9, 6),
    ("Profetas", "media", "Os que esperam no Senhor renovarão as suas forças.", "Isaías", 40, 31),
    ("Profetas", "media", "Não vos lembreis das coisas passadas.", "Isaías", 43, 18),
    ("Profetas", "media", "Buscai-me e vivereis.", "Amós", 5, 4),
    ("Profetas", "dificil", "Como são formosos os pés dos que anunciam o evangelho.", "Isaías", 52, 7),
    ("Profetas", "dificil", "Dar-vos-ei coração novo e porei dentro de vós espírito novo.", "Ezequiel", 36, 26),
    ("Profetas", "dificil", "Vós sereis a minha porção.", "Jeremias", 10, 16),
    ("Profetas", "media", "Porque eu bem sei os pensamentos que penso de vós.", "Jeremias", 29, 11),
    ("Profetas", "dificil", "Converta-se o ímpio do seu caminho.", "Ezequiel", 33, 11),

    # ===== HISTÓRICOS (10) =====
    ("Históricos", "facil", "O Senhor é contigo varão valoroso.", "Juízes", 6, 12),
    ("Históricos", "media", "Escolhei hoje a quem sirvais.", "Josué", 24, 15),
    ("Históricos", "media", "Sê forte e corajoso.", "Josué", 1, 9),
    ("Históricos", "media", "O Senhor não vê como vê o homem.", "1 Samuel", 16, 7),
    ("Históricos", "dificil", "Tua casa e teu reino serão firmados para sempre.", "2 Samuel", 7, 16),
    ("Históricos", "dificil", "Se o meu povo que se chama pelo meu nome se humilhar.", "2 Crônicas", 7, 14),
    ("Históricos", "media", "Tudo pode o que confia em Deus.", "Mateus", 19, 26),
    ("Históricos", "dificil", "Eu sou o Senhor e não há outro.", "Isaías", 45, 5),
    ("Históricos", "media", "Confia no Senhor de todo o teu coração.", "Provérbios", 3, 5),
    ("Históricos", "dificil", "Para o homem é impossível mas para Deus tudo é possível.", "Mateus", 19, 26),

    # ===== SABEDORIA (10) =====
    ("Sabedoria", "facil", "Guarda o teu coração com toda a diligência.", "Provérbios", 4, 23),
    ("Sabedoria", "facil", "O temor do Senhor é o princípio do conhecimento.", "Provérbios", 1, 7),
    ("Sabedoria", "facil", "Confia no Senhor e faze o bem.", "Salmos", 37, 3),
    ("Sabedoria", "media", "Vaidade de vaidades tudo é vaidade.", "Eclesiastes", 1, 2),
    ("Sabedoria", "media", "Melhor é a sabedoria que a força.", "Eclesiastes", 9, 16),
    ("Sabedoria", "media", "A resposta branda desvia o furor.", "Provérbios", 15, 1),
    ("Sabedoria", "dificil", "O orgulho vai adiante da ruína.", "Provérbios", 16, 18),
    ("Sabedoria", "dificil", "Instrui o menino no caminho em que deve andar.", "Provérbios", 22, 6),
    ("Sabedoria", "media", "Em todo tempo ama o amigo.", "Provérbios", 17, 17),
    ("Sabedoria", "dificil", "Não te glories do dia de amanhã.", "Provérbios", 27, 1),

    # ===== REFERÊNCIAS EXPLÍCITAS (5) =====
    ("Explícitas", "facil", "Provérbios 15:14", "Provérbios", 15, 14),
    ("Explícitas", "facil", "João 3:16", "João", 3, 16),
    ("Explícitas", "facil", "Salmos 23", "Salmos", 23, 0),
    ("Explícitas", "facil", "Romanos 8:28", "Romanos", 8, 28),
    ("Explícitas", "facil", "Filipenses 4:13", "Filipenses", 4, 13),
]

# Frases dependentes de contexto (separadas, com referência esperada condicional)
# Para essas frases, o "esperado" depende do recent_text.
# Vamos definir pares (frase, recent_text, livro_esperado, cap, vers)
CORPUS_CONTEXTUAL = [
    ("Como vimos anteriormente.", "O Senhor é meu pastor.", "Salmos", 23, 0),
    ("Esse mesmo versículo.", "Porque Deus amou o mundo.", "João", 3, 16),
    ("No capítulo anterior.", "Tudo posso naquele que me fortalece.", "Filipenses", 4, 0),
    ("A mesma passagem.", "A armadura de Deus.", "Efésios", 6, 0),
    ("Voltando ao texto.", "Guarda o teu coração.", "Provérbios", 4, 23),
]
