--
-- PostgreSQL database dump
--

\restrict 3bXntJM2nWKRKIpVPFFHjea6v3mP07PyxksucVdSu2ZKYUo76oSeQOlQBZhnUOy

-- Dumped from database version 17.7 (Debian 17.7-3.pgdg13+1)
-- Dumped by pg_dump version 17.7 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: is_tt_window_open(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.is_tt_window_open() RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
    now_local TIME;
    active_event RECORD;
BEGIN
    now_local := (NOW() AT TIME ZONE 'Africa/Johannesburg')::TIME;

    SELECT *
    INTO active_event
    FROM tt_events
    WHERE event_date = CURRENT_DATE
      AND active = true
    LIMIT 1;

    IF NOT FOUND THEN
        RETURN false;
    END IF;

    RETURN now_local BETWEEN active_event.start_time AND active_event.end_time;
END;
$$;


ALTER FUNCTION public.is_tt_window_open() OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: event_codes; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.event_codes (
    id integer NOT NULL,
    event text NOT NULL,
    code text NOT NULL,
    event_date date NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.event_codes OWNER TO postgres;

--
-- Name: event_codes_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.event_codes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.event_codes_id_seq OWNER TO postgres;

--
-- Name: event_codes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.event_codes_id_seq OWNED BY public.event_codes.id;


--
-- Name: event_config; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.event_config (
    id integer NOT NULL,
    event text NOT NULL,
    day_of_week integer NOT NULL,
    open_time text NOT NULL,
    close_time text NOT NULL,
    active boolean DEFAULT true,
    submissions_open boolean DEFAULT false
);


ALTER TABLE public.event_config OWNER TO postgres;

--
-- Name: event_config_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.event_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.event_config_id_seq OWNER TO postgres;

--
-- Name: event_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.event_config_id_seq OWNED BY public.event_config.id;


--
-- Name: members; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.members (
    id integer NOT NULL,
    phone text NOT NULL,
    first_name text,
    last_name text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    participation_type text,
    pending_distance text,
    leaderboard_opt_out boolean DEFAULT false,
    popia_acknowledged boolean DEFAULT false
);


ALTER TABLE public.members OWNER TO postgres;

--
-- Name: members_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.members_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.members_id_seq OWNER TO postgres;

--
-- Name: members_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.members_id_seq OWNED BY public.members.id;


--
-- Name: submissions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.submissions (
    id integer NOT NULL,
    member_id integer NOT NULL,
    activity text DEFAULT 'TT'::text,
    distance_text text,
    time_text text,
    seconds integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    mode text DEFAULT 'RUN'::text NOT NULL,
    confirmed boolean DEFAULT false NOT NULL,
    updated_at timestamp without time zone,
    tt_code_verified boolean DEFAULT false,
    code_used text,
    status text DEFAULT 'PENDING'::text,
    tt_code text,
    admin_note text
);


ALTER TABLE public.submissions OWNER TO postgres;

--
-- Name: submissions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.submissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.submissions_id_seq OWNER TO postgres;

--
-- Name: submissions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.submissions_id_seq OWNED BY public.submissions.id;


--
-- Name: tt_events; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.tt_events (
    id integer NOT NULL,
    event_date date NOT NULL,
    start_time time without time zone NOT NULL,
    end_time time without time zone NOT NULL,
    timezone text DEFAULT 'Africa/Johannesburg'::text NOT NULL,
    active boolean DEFAULT true NOT NULL
);


ALTER TABLE public.tt_events OWNER TO postgres;

--
-- Name: tt_events_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tt_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tt_events_id_seq OWNER TO postgres;

--
-- Name: tt_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tt_events_id_seq OWNED BY public.tt_events.id;


--
-- Name: event_codes id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.event_codes ALTER COLUMN id SET DEFAULT nextval('public.event_codes_id_seq'::regclass);


--
-- Name: event_config id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.event_config ALTER COLUMN id SET DEFAULT nextval('public.event_config_id_seq'::regclass);


--
-- Name: members id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.members ALTER COLUMN id SET DEFAULT nextval('public.members_id_seq'::regclass);


--
-- Name: submissions id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.submissions ALTER COLUMN id SET DEFAULT nextval('public.submissions_id_seq'::regclass);


--
-- Name: tt_events id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tt_events ALTER COLUMN id SET DEFAULT nextval('public.tt_events_id_seq'::regclass);


--
-- Data for Name: event_codes; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.event_codes (id, event, code, event_date, created_at) FROM stdin;
1	TT	TT123	2026-01-06	2026-01-06 04:17:42.034634
2	TT	U1GEMW	2026-01-06	2026-01-06 07:03:20.902557
3	WEDLSD	W15ZQ6	2026-01-06	2026-01-06 08:24:30.136463
4	TT	L63HG0	2026-01-06	2026-01-06 08:41:40.26988
5	TT	QR3XCZ	2026-01-06	2026-01-06 09:34:17.938333
6	TT	H6JQD7	2026-01-06	2026-01-06 09:39:21.993705
7	TT	8OCCHH	2026-01-06	2026-01-06 09:50:18.483107
8	TT	O5PIFO	2026-01-06	2026-01-06 10:39:57.385247
9	TT	T93UG6	2026-01-06	2026-01-06 11:16:31.316478
10	TT	HZOQHR	2026-01-06	2026-01-06 14:20:30.047696
11	TT	Q1HP7Q	2026-01-06	2026-01-06 14:45:55.663136
12	TT	39EIKJ	2026-01-06	2026-01-06 15:01:53.296778
13	TT	SBK03E	2026-01-06	2026-01-06 15:23:12.381659
14	TT	7460	2026-01-13	2026-01-13 11:15:27.583288
\.


--
-- Data for Name: event_config; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.event_config (id, event, day_of_week, open_time, close_time, active, submissions_open) FROM stdin;
2	WEDLSD	3	17:00	22:00	f	f
3	SUNSOCIAL	0	05:30	22:00	f	f
1	TT	2	17:00	22:00	t	f
\.


--
-- Data for Name: members; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.members (id, phone, first_name, last_name, created_at, participation_type, pending_distance, leaderboard_opt_out, popia_acknowledged) FROM stdin;
2	27605283912	Unknown	Member	2026-01-05 20:21:58.337863	BOTH	\N	f	f
3	27832805524	Unknown	Member	2026-01-06 10:46:58.275129	RUNNER	\N	f	f
4	27825528227	Unknown	Member	2026-01-06 10:47:40.255218	RUNNER	\N	f	f
5	27829370733	Unknown	Member	2026-01-06 10:50:26.931218	WALKER	\N	f	f
6	27824974605	Unknown	Member	2026-01-06 10:56:42.053351	RUNNER	\N	f	f
64	27790385688	Unknown	Member	2026-01-06 14:54:22.030728	RUNNER	\N	f	t
70	27605473353	Unknown	Member	2026-01-06 15:41:23.69462	RUNNER	\N	f	t
10	27639259085	Unknown	Member	2026-01-06 10:58:08.538984	RUNNER	\N	f	f
11	27725733553	Unknown	Member	2026-01-06 10:58:28.015112	RUNNER	\N	f	f
84	27832844884	Unknown	Member	2026-01-06 16:46:31.979249	RUNNER	\N	f	t
9	27711616333	Unknown	Member	2026-01-06 10:58:03.633451	RUNNER	\N	f	t
14	27824681537	Unknown	Member	2026-01-06 11:17:42.787717	RUNNER	\N	f	f
176	27825651219	Emile	Myburgh	2026-01-13 16:25:13.4941	RUNNER	\N	f	t
169	27721042286	Retha	Knoetze	2026-01-13 16:15:33.741433	WALKER	\N	f	t
17	27832006441	Unknown	Member	2026-01-06 11:27:23.340299	RUNNER	\N	f	f
18	27823276844	Unknown	Member	2026-01-06 11:31:42.276277	RUNNER	\N	f	f
19	27793945101	Unknown	Member	2026-01-06 11:57:34.843679	RUNNER	\N	f	f
26	27824739434	Unknown	Member	2026-01-06 12:26:49.414106	RUNNER	\N	f	t
21	27828862482	Unknown	Member	2026-01-06 12:01:16.73847	RUNNER	\N	f	f
22	27824963138	Unknown	Member	2026-01-06 12:05:40.082993	RUNNER	\N	f	f
83	27673429555	Unknown	Member	2026-01-06 16:42:37.928918	RUNNER	\N	f	t
25	27769991384	Unknown	Member	2026-01-06 12:23:20.885372	WALKER	\N	f	f
85	27826044441	Unknown	Member	2026-01-06 16:47:44.593869	RUNNER	\N	f	t
88	27609925330	Unknown	Member	2026-01-06 17:05:45.049308	RUNNER	\N	f	t
32	27609749290	Unknown	Member	2026-01-06 13:29:12.810993	RUNNER	\N	f	t
16	27828532164	Unknown	Member	2026-01-06 11:25:13.270378	RUNNER	\N	f	t
82	27829406073	Unknown	Member	2026-01-06 16:29:30.659129	RUNNER	\N	f	t
79	27769067862	Mariette	van Niekerk	2026-01-06 16:25:44.251943	RUNNER	\N	f	f
171	27725161127	Hannes	Lerm	2026-01-13 16:20:14.329881	RUNNER	\N	f	t
31	27634045059	Unknown	Member	2026-01-06 13:25:13.324313	RUNNER	\N	f	f
30	27722284540	Unknown	Member	2026-01-06 13:13:00.695061	RUNNER	\N	f	t
65	27769852475	Unknown	Member	2026-01-06 14:54:59.866798	RUNNER	\N	f	f
66	27825528772	Unknown	Member	2026-01-06 15:07:41.082478	RUNNER	\N	f	f
68	27832637248	Unknown	Member	2026-01-06 15:12:47.640241	RUNNER	\N	f	f
181	27825544700	Johan	de Klerk	2026-01-13 16:28:46.588619	RUNNER	\N	f	t
75	27722487698	Unknown	Member	2026-01-06 16:13:43.923259	RUNNER	\N	f	t
71	27828296669	Unknown	Member	2026-01-06 15:45:55.319715	RUNNER	\N	f	f
20	27822228365	Unknown	Member	2026-01-06 11:58:30.051274	WALKER	\N	f	t
8	27783491786	Unknown	Member	2026-01-06 10:57:48.850277	RUNNER	\N	f	t
80	27833209119	Unknown	Member	2026-01-06 16:26:15.653605	RUNNER	\N	f	f
76	27718738879	Unknown	Member	2026-01-06 16:16:21.983782	RUNNER	\N	f	t
90	27729513962	Unknown	Member	2026-01-06 17:28:26.240337	RUNNER	\N	f	t
87	27824979367	Unknown	Member	2026-01-06 17:05:16.381653	WALKER	\N	f	t
173	27836809033	Mignon	Makris	2026-01-13 16:21:15.34928	RUNNER	\N	f	t
78	27735540803	Unknown	Member	2026-01-06 16:19:59.773501	RUNNER	\N	f	t
89	27827800081	Unknown	Member	2026-01-06 17:08:06.677587	BOTH	\N	f	f
81	27824958185	Unknown	Member	2026-01-06 16:28:16.229728	RUNNER	\N	f	t
165	27812222020	Lance	Van Der Scholtz	2026-01-13 16:09:46.045819	RUNNER	\N	f	t
92	27761461461	Unknown	Member	2026-01-06 18:47:11.894994	RUNNER	\N	f	f
67	27835096203	Unknown	Member	2026-01-06 15:12:29.659597	RUNNER	\N	f	f
94	27605261625	Unknown	Member	2026-01-07 07:04:47.070997	RUNNER	\N	f	f
95	27812535030	Unknown	Member	2026-01-07 11:08:09.385341	RUNNER	\N	f	f
96	27826738204	Unknown	Member	2026-01-07 12:08:07.039131	RUNNER	\N	f	f
93	27787255480	Unknown	Member	2026-01-07 04:40:40.832906	RUNNER	\N	f	f
1	27722135094	Lindsay	Bull	2026-01-05 16:16:06.413165	RUNNER	4km	f	t
77	27824481323	Unknown	Member	2026-01-06 16:18:30.225807	RUNNER	\N	f	t
91	27836567926	Unknown	Member	2026-01-06 17:41:58.926515	BOTH	\N	f	t
24	27794962387	Unknown	Member	2026-01-06 12:12:16.105215	RUNNER	\N	f	t
172	27712198854	Andre	Gerber	2026-01-13 16:20:35.728343	RUNNER	\N	f	t
164	27832326062	Suzanne	Casey	2026-01-13 16:07:06.570457	RUNNER	\N	f	t
163	27823380590	Myrna	van Wyk	2026-01-13 16:06:53.447522	RUNNER	\N	f	t
7	27714921228	Unknown	Member	2026-01-06 10:57:01.346336	RUNNER	\N	f	t
167	27845572774	Tayla	Macaskill	2026-01-13 16:11:44.480404	RUNNER	\N	f	t
72	27825642545	Unknown	Member	2026-01-06 15:46:17.568267	RUNNER	\N	f	t
170	27829695924	Alex	Elsworth	2026-01-13 16:19:31.187418	RUNNER	\N	f	t
168	27839855595	Nico	le Roux	2026-01-13 16:13:15.158413	RUNNER	\N	f	t
166	27646572713	Johan	Jnr Janse van Vuuren	2026-01-13 16:11:37.277425	RUNNER	\N	f	t
28	27763128753	Unknown	Member	2026-01-06 12:35:32.503097	RUNNER	\N	f	t
27	27833349116	Unknown	Member	2026-01-06 12:26:58.214121	RUNNER	\N	f	t
177	27825545659	TRACY	THOMPSON	2026-01-13 16:25:32.06947	WALKER	\N	f	t
178	27713651783	Yolandé	Bezuidenhout	2026-01-13 16:27:21.076681	BOTH	\N	f	t
175	27630228649	Londani	Shirilele	2026-01-13 16:24:40.083806	RUNNER	\N	f	t
182	27762965448	Nadia	Nel	2026-01-13 16:29:08.420302	RUNNER	\N	f	t
174	27828590330	Mpho	Mathekga	2026-01-13 16:22:30.348024	RUNNER	\N	f	t
15	27829791864	Unknown	Member	2026-01-06 11:19:13.646756	RUNNER	\N	f	t
69	27738870757	Unknown	Member	2026-01-06 15:20:24.028452	RUNNER	\N	f	t
63	27725957859	Unknown	Member	2026-01-06 14:48:05.577968	RUNNER	\N	f	t
179	27718698841	Jacques	Bannister	2026-01-13 16:27:58.983813	RUNNER	\N	f	t
23	27848022991	Unknown	Member	2026-01-06 12:05:51.334003	BOTH	\N	f	t
180	27718538288	Lawson	Kunzmann	2026-01-13 16:28:38.793607	RUNNER	\N	f	t
183	27823312236	Estien	van Wyngaard	2026-01-13 16:31:16.869068	WALKER	\N	f	t
74	27824940077	Unknown	Member	2026-01-06 16:08:50.222489	RUNNER	\N	f	t
73	27832794122	Unknown	Member	2026-01-06 15:47:20.651078	RUNNER	\N	f	t
185	27716002708	Pieter	Pretorius	2026-01-13 16:36:08.28049	RUNNER	\N	f	t
186	27826713800	\N	\N	2026-01-13 16:36:25.174518	\N	\N	f	f
187	27825655895	Tania	Thompson	2026-01-13 16:36:51.417717	WALKER	\N	f	t
29	27794999499	Unknown	Member	2026-01-06 13:11:34.34482	RUNNER	\N	f	t
184	27798946092	Reghardt	Pieterse	2026-01-13 16:32:57.891237	RUNNER	\N	f	t
188	27828559465	Heimar	Beukes	2026-01-13 16:37:54.774309	RUNNER	\N	f	t
189	27825640088	Melani	Swart	2026-01-13 16:39:34.322644	RUNNER	\N	f	t
190	27823123540	Elisna	Houy	2026-01-13 16:40:14.386102	RUNNER	\N	f	t
12	27827872630	Unknown	Member	2026-01-06 11:05:42.67633	RUNNER	\N	f	t
191	27825514160	Fanna	Njomo	2026-01-13 16:44:47.59632	RUNNER	\N	f	t
192	27734524684	Natasha	Pienaar	2026-01-13 16:45:56.472937	RUNNER	\N	f	t
193	27646806088	Ané	Vos	2026-01-13 17:04:15.033701	RUNNER	\N	f	t
194	27833051003	Cari	Snyman	2026-01-13 17:13:19.109822	RUNNER	\N	f	t
86	27721004166	Unknown	Member	2026-01-06 16:53:12.502024	RUNNER	\N	f	t
196	27798822082	Neël	Swanepoel	2026-01-13 17:39:37.125321	RUNNER	\N	f	t
197	27822675000	Rykie	Kruger	2026-01-13 18:02:05.428556	RUNNER	\N	f	t
198	27827876272	Ané	Pieterse	2026-01-13 18:08:33.632862	RUNNER	\N	f	t
13	27794789795	Unknown	Member	2026-01-06 11:10:37.176859	RUNNER	\N	f	t
199	27714127887	Henry	Enslin	2026-01-13 19:11:29.845073	RUNNER	\N	f	t
195	27826391599	Johann	Coetzee	2026-01-13 17:37:04.489032	WALKER	\N	f	t
200	27832661133	Jaap	Willemse	2026-01-13 19:32:01.525417	WALKER	\N	f	t
201	27664145120	Matome	Ramachela	2026-01-13 20:10:57.470993	RUNNER	\N	f	t
202	27814760279	\N	\N	2026-01-13 20:18:18.367662	\N	\N	f	f
203	27745281465	Tony	Makris	2026-01-15 06:58:13.127642	\N	\N	f	t
\.


--
-- Data for Name: submissions; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.submissions (id, member_id, activity, distance_text, time_text, seconds, created_at, mode, confirmed, updated_at, tt_code_verified, code_used, status, tt_code, admin_note) FROM stdin;
349	10	TT	4km	00:30:53	1853	2026-01-06 16:35:27	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
350	9	TT	8km	00:48:48	2928	2026-01-06 16:31:48	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
351	76	TT	4km	00:27:35	1655	2026-01-06 16:17:22	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
352	86	TT	8km	00:36:03	2163	2026-01-06 16:56:26	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
353	1	TT	4km	00:27:11	1631	2026-01-06 15:27:40	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
354	75	TT	8km	00:35:29	2129	2026-01-06 16:22:10	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
355	63	TT	6km	00:54:44	3284	2026-01-06 16:52:46	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
356	78	TT	8km	00:39:18	2358	2026-01-06 16:23:10	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
357	69	TT	4km	00:25:30	1530	2026-01-06 16:20:02	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
358	28	TT	8km	00:35:31	2131	2026-01-06 16:16:44	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
359	79	TT	8km	00:47:30	2850	2026-01-06 16:34:21	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
361	64	TT	6km	00:39:53	2393	2026-01-06 16:33:08	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
362	19	TT	8km	00:54:59	3299	2026-01-06 16:36:55	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
363	13	TT	8km	00:48:48	2928	2026-01-06 16:52:52	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
364	20	TT	8km	01:14:54	4494	2026-01-06 16:25:11	WALKER	t	\N	f	\N	COMPLETE	\N	\N
365	77	TT	8km	00:39:03	2343	2026-01-06 16:24:31	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
366	74	TT	6km	00:35:06	2106	2026-01-06 16:34:42	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
367	81	TT	8km	00:46:10	2770	2026-01-06 16:31:28	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
368	72	TT	8km	00:19:33	1173	2026-01-06 15:52:52	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
369	82	TT	8km	00:50:32	3032	2026-01-06 16:37:45	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
370	15	TT	6km	00:28:35	1715	2026-01-06 16:17:14	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
371	3	TT	6km	00:34:43	2083	2026-01-06 16:13:54	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
372	80	TT	6km	00:40:43	2443	2026-01-06 16:31:48	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
437	188	TT	8	50:25	3025	2026-01-13 16:38:58.314433	RUN	t	\N	t	\N	COMPLETE	7460	\N
394	24	TT	4	28:33	1713	2026-01-13 16:06:23.689762	RUN	t	\N	t	\N	COMPLETE	7460	\N
373	23	TT	6km	00:47:21	2841	2026-01-06 16:26:26	BOTH	t	\N	f	\N	COMPLETE	\N	\N
348	31	TT	8km	00:47:57	2877	2026-01-06 16:40:17	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
360	8	TT	6km	00:39:53	2393	2026-01-06 16:40:57	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
374	96	TT	4km	00:34:39	2079	2026-01-06 00:00:00	RUN	t	\N	f	\N	COMPLETE	\N	\N
375	67	TT	8km	00:41:46	2506	2026-01-06 00:00:00	RUN	t	\N	f	\N	COMPLETE	\N	\N
376	26	TT	8km	00:44:49	2689	2026-01-06 00:00:00	RUN	t	\N	f	\N	COMPLETE	\N	\N
423	63	TT	6	51:33	3093	2026-01-13 16:28:54.977428	RUN	t	\N	t	\N	COMPLETE	7460	\N
411	75	TT	8	36:10	2170	2026-01-13 16:18:39.302243	RUN	t	\N	t	\N	COMPLETE	7460	\N
449	76	TT	6	35:18	2118	2026-01-13 16:50:01.215787	RUN	t	\N	t	\N	COMPLETE	7460	\N
408	88	TT	4	29:15	1755	2026-01-13 16:16:55.889518	RUN	t	\N	t	\N	COMPLETE	7460	\N
393	91	TT	6	55:24	3324	2026-01-13 15:23:49.412434	RUN	t	\N	t	\N	COMPLETE	7460	\N
425	179	TT	8	43:58	2638	2026-01-13 16:29:17.222297	RUN	t	\N	t	\N	COMPLETE	7460	\N
398	7	TT	6	33:12	1992	2026-01-13 16:10:21.33067	RUN	t	\N	t	\N	COMPLETE	7460	\N
410	32	TT	6	34:32	2072	2026-01-13 16:17:49.59063	RUN	t	\N	t	\N	COMPLETE	7460	\N
391	1	TT	4	21:30	1290	2026-01-13 13:06:37.051089	RUN	t	\N	t	\N	COMPLETE	7460	\N
396	163	TT	4	28:34	1714	2026-01-13 16:09:43.473446	RUN	t	\N	t	\N	COMPLETE	7460	\N
427	181	TT	8	43:35	2615	2026-01-13 16:29:47.455114	RUN	t	\N	t	\N	COMPLETE	7460	\N
400	165	TT	4	33:10	1990	2026-01-13 16:10:48.384283	RUN	t	\N	t	\N	COMPLETE	7460	\N
413	173	TT	4	21:24	1284	2026-01-13 16:21:51.817034	RUN	t	\N	t	\N	COMPLETE	7460	\N
402	72	TT	8	1:16:15	4575	2026-01-13 16:13:21.376196	RUN	t	\N	t	\N	COMPLETE	7460	\N
395	164	TT	4	26:24	1584	2026-01-13 16:09:23.1906	RUN	t	\N	t	\N	COMPLETE	7460	\N
399	164	TT	\N	\N	\N	2026-01-13 16:10:23.989987	RUN	t	\N	f	\N	PENDING	\N	\N
1	68	TT	5km	25:30	1530	2026-01-06 19:10:09.880094	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
2	68	TT	5km	25:30	1530	2026-01-06 19:10:53.61677	RUNNER	t	\N	f	\N	COMPLETE	\N	\N
442	182	TT	8	48:18	2898	2026-01-13 16:41:58.404168	RUN	t	\N	t	\N	COMPLETE	7460	\N
440	190	TT	8	47:24	2844	2026-01-13 16:41:25.349417	RUN	t	\N	t	\N	COMPLETE	7460	\N
412	170	TT	8	00:40:41	2441	2026-01-13 16:20:37.660537	RUN	t	\N	t	\N	COMPLETE	7460	\N
392	77	TT	8	42:33	2553	2026-01-13 14:26:18.094856	RUN	t	\N	t	\N	PENDING	7460	\N
397	16	TT	4	25:33	1533	2026-01-13 16:10:13.541514	RUN	t	\N	t	\N	COMPLETE	7460	\N
401	167	TT	4	28:27	1707	2026-01-13 16:12:35.095915	RUN	t	\N	t	\N	COMPLETE	7460	\N
414	171	TT	8	40:32	2432	2026-01-13 16:22:27.869084	RUN	t	\N	t	\N	COMPLETE	7460	\N
403	168	TT	4	28:42	1722	2026-01-13 16:14:02.63527	RUN	t	\N	t	\N	COMPLETE	7460	\N
444	81	TT	8	47:00	2820	2026-01-13 16:43:53.541721	RUN	t	\N	t	\N	COMPLETE	7460	\N
405	28	TT	8	35:05	2105	2026-01-13 16:14:15.317356	RUN	t	\N	t	\N	COMPLETE	7460	\N
416	174	TT	6	48:00	2880	2026-01-13 16:23:11.773462	RUN	t	\N	t	\N	COMPLETE	7460	\N
407	169	TT	4	30:50	1850	2026-01-13 16:16:35.33176	RUN	t	\N	t	\N	COMPLETE	7460	\N
409	83	TT	6	34:47	2087	2026-01-13 16:16:56.741987	RUN	t	\N	t	\N	COMPLETE	7460	\N
446	191	TT	8	69:00	4140	2026-01-13 16:45:55.52568	RUN	t	\N	t	\N	COMPLETE	7460	\N
420	176	TT	6	39:30	2370	2026-01-13 16:26:36.520504	RUN	t	\N	t	\N	COMPLETE	7460	\N
418	175	TT	8	46:04	2764	2026-01-13 16:26:29.158969	RUN	t	\N	t	\N	COMPLETE	7460	\N
448	84	TT	8	47:41	2861	2026-01-13 16:47:58.415747	RUN	t	\N	t	\N	COMPLETE	7460	\N
422	178	TT	4	29:12	1752	2026-01-13 16:28:18.442627	RUN	t	\N	t	\N	COMPLETE	7460	\N
450	26	TT	8	45:29	2729	2026-01-13 16:58:19.936717	RUN	t	\N	t	\N	COMPLETE	7460	\N
424	69	TT	6	38:16	2296	2026-01-13 16:28:59.299343	RUN	t	\N	t	\N	COMPLETE	7460	\N
452	193	TT	\N	\N	\N	2026-01-13 17:06:13.958191	RUN	t	\N	f	\N	PENDING	\N	\N
426	180	TT	8	50:43	3043	2026-01-13 16:29:30.058605	RUN	t	\N	t	\N	COMPLETE	7460	\N
428	23	TT	6	47:28	2848	2026-01-13 16:30:34.480358	RUN	t	\N	t	\N	COMPLETE	7460	\N
454	78	TT	8	47:33	2853	2026-01-13 17:40:27.389255	RUN	t	\N	t	\N	COMPLETE	7460	\N
430	74	TT	8	00:53:06	3186	2026-01-13 16:32:32.717547	RUN	t	\N	t	\N	COMPLETE	7460	\N
432	173	TT	\N	\N	\N	2026-01-13 16:34:02.727636	RUN	t	\N	f	\N	PENDING	\N	\N
439	189	TT	8	50:25	3025	2026-01-13 16:40:57.797349	RUN	t	\N	t	\N	COMPLETE	7460	\N
404	166	TT	4	00:19:16	1156	2026-01-13 16:14:06.656339	RUN	t	\N	t	\N	COMPLETE	7460	\N
417	171	TT	\N	\N	\N	2026-01-13 16:23:22.713552	RUN	t	\N	f	\N	PENDING	\N	\N
429	183	TT	6	46:09	2769	2026-01-13 16:32:29.83518	RUN	t	\N	t	\N	COMPLETE	7460	\N
415	172	TT	8	38:30	2310	2026-01-13 16:22:50.991725	RUN	t	\N	t	\N	COMPLETE	7460	\N
406	27	TT	6	39:02	2342	2026-01-13 16:15:11.81154	RUN	t	\N	t	\N	COMPLETE	7460	\N
441	82	TT	8	49:47	2987	2026-01-13 16:41:34.921687	RUN	t	\N	t	\N	COMPLETE	7460	\N
461	199	TT	8	34:45	2085	2026-01-13 19:12:23.837578	RUN	t	\N	t	\N	COMPLETE	7460	\N
419	15	TT	6	33:35	2015	2026-01-13 16:26:29.920403	RUN	t	\N	t	\N	COMPLETE	7460	\N
443	90	TT	8	44:12	2652	2026-01-13 16:42:20.447735	RUN	t	\N	t	\N	COMPLETE	7460	\N
421	177	TT	4	39:06	2346	2026-01-13 16:26:44.132867	RUN	t	\N	t	\N	COMPLETE	7460	\N
433	87	TT	4	42:34	2554	2026-01-13 16:36:14.026702	RUN	t	\N	t	\N	COMPLETE	7460	\N
451	85	TT	8	48:05	2885	2026-01-13 17:02:10.114163	RUN	t	\N	t	\N	COMPLETE	7460	\N
457	198	TT	8	47:19	2839	2026-01-13 18:09:45.731517	RUN	t	\N	t	\N	COMPLETE	7460	\N
445	12	TT	8	47:00	2820	2026-01-13 16:44:48.316033	RUN	t	\N	t	\N	COMPLETE	7460	\N
435	184	TT	4	29:40	1780	2026-01-13 16:38:14.659285	RUN	t	\N	t	\N	COMPLETE	7460	\N
453	194	TT	8	54:45	3285	2026-01-13 17:14:41.895833	RUN	t	\N	t	\N	COMPLETE	7460	\N
456	197	TT	8	38:41	2321	2026-01-13 18:03:09.399663	RUN	t	\N	t	\N	COMPLETE	7460	\N
434	187	TT	4	30:00	1800	2026-01-13 16:37:43.702456	RUN	t	\N	t	\N	COMPLETE	7460	\N
436	185	TT	8	44:22	2662	2026-01-13 16:38:19.270789	RUN	t	\N	t	\N	COMPLETE	7460	\N
438	29	TT	6	49:43	2983	2026-01-13 16:39:00.613312	RUN	t	\N	t	\N	COMPLETE	7460	\N
460	13	TT	8	45:19	2719	2026-01-13 18:58:42.622269	RUN	t	\N	t	\N	COMPLETE	7460	\N
458	64	TT	6	42:09	2529	2026-01-13 18:43:48.517819	RUN	t	\N	t	\N	COMPLETE	7460	\N
447	192	TT	8	46:58	2818	2026-01-13 16:47:40.588085	RUN	t	\N	t	\N	COMPLETE	7460	\N
431	73	TT	8	50:31	3031	2026-01-13 16:33:22.535692	RUN	t	\N	t	\N	COMPLETE	7460	\N
459	30	TT	6	37:51	2271	2026-01-13 18:44:49.181504	RUN	t	\N	t	\N	COMPLETE	7460	\N
455	196	TT	8	47:33	2853	2026-01-13 17:40:36.567344	RUN	t	\N	t	\N	COMPLETE	7460	\N
462	195	TT	\N	\N	\N	2026-01-13 19:13:10.709906	RUN	t	\N	t	\N	PENDING	7460	\N
465	203	TT	4	16:59	1019	2026-01-13 18:30:00	RUN	t	\N	t	\N	PENDING	\N	Manual admin capture – missed cutoff
466	79	TT	6	33:10	1990	2026-01-13 18:30:00	RUN	t	\N	t	\N	PENDING	\N	Manual admin capture – missed cutoff
463	200	TT	4	27:17	1637	2026-01-13 19:33:45.867185	RUN	t	\N	t	\N	COMPLETE	7460	\N
464	201	TT	\N	\N	\N	2026-01-13 20:13:15.940567	RUN	t	\N	f	\N	PENDING	\N	\N
\.


--
-- Data for Name: tt_events; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.tt_events (id, event_date, start_time, end_time, timezone, active) FROM stdin;
1	2026-01-06	16:30:00	22:30:00	Africa/Johannesburg	t
\.


--
-- Name: event_codes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.event_codes_id_seq', 14, true);


--
-- Name: event_config_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.event_config_id_seq', 3, true);


--
-- Name: members_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.members_id_seq', 204, true);


--
-- Name: submissions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.submissions_id_seq', 466, true);


--
-- Name: tt_events_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.tt_events_id_seq', 1, true);


--
-- Name: event_codes event_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.event_codes
    ADD CONSTRAINT event_codes_pkey PRIMARY KEY (id);


--
-- Name: event_config event_config_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.event_config
    ADD CONSTRAINT event_config_pkey PRIMARY KEY (id);


--
-- Name: members members_phone_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.members
    ADD CONSTRAINT members_phone_key UNIQUE (phone);


--
-- Name: members members_phone_unique; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.members
    ADD CONSTRAINT members_phone_unique UNIQUE (phone);


--
-- Name: members members_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.members
    ADD CONSTRAINT members_pkey PRIMARY KEY (id);


--
-- Name: submissions submissions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.submissions
    ADD CONSTRAINT submissions_pkey PRIMARY KEY (id);


--
-- Name: tt_events tt_events_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tt_events
    ADD CONSTRAINT tt_events_pkey PRIMARY KEY (id);


--
-- Name: submissions submissions_member_fk; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.submissions
    ADD CONSTRAINT submissions_member_fk FOREIGN KEY (member_id) REFERENCES public.members(id) ON DELETE CASCADE;


--
-- Name: submissions submissions_member_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.submissions
    ADD CONSTRAINT submissions_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(id);


--
-- PostgreSQL database dump complete
--

\unrestrict 3bXntJM2nWKRKIpVPFFHjea6v3mP07PyxksucVdSu2ZKYUo76oSeQOlQBZhnUOy

