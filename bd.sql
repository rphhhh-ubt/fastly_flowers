--
-- PostgreSQL database dump
--

\restrict y9GQXw9JCD2ZFc8a0fzWbKpInWCoWyIv9ChvDlN2pyGAy85FR84534Vk7dPLFop

-- Dumped from database version 14.19 (Ubuntu 14.19-0ubuntu0.22.04.1)
-- Dumped by pg_dump version 14.19 (Ubuntu 14.19-0ubuntu0.22.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: account_groups; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.account_groups (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    emoji character varying(10)
);


ALTER TABLE public.account_groups OWNER TO postgres;

--
-- Name: account_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.account_groups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.account_groups_id_seq OWNER TO postgres;

--
-- Name: account_groups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.account_groups_id_seq OWNED BY public.account_groups.id;


--
-- Name: account_session_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.account_session_history (
    id integer NOT NULL,
    account_id integer NOT NULL,
    old_session text,
    changed_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.account_session_history OWNER TO postgres;

--
-- Name: account_session_history_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.account_session_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.account_session_history_id_seq OWNER TO postgres;

--
-- Name: account_session_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.account_session_history_id_seq OWNED BY public.account_session_history.id;


--
-- Name: accounts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.accounts (
    id integer NOT NULL,
    phone_number character varying(20),
    proxy_type character varying(10),
    proxy_host character varying(100),
    proxy_port integer,
    proxy_username character varying(100),
    proxy_password character varying(100),
    status character varying(50) DEFAULT 'new'::character varying,
    created_at timestamp without time zone DEFAULT now(),
    api_key_id integer,
    session_string text,
    label text,
    phone text,
    username text,
    is_spam_blocked boolean DEFAULT false,
    spam_block_until timestamp without time zone,
    spam_block_reason text,
    proxy_status character varying(20),
    group_id integer,
    first_name text,
    last_name text,
    spam_checked_at timestamp without time zone,
    banned boolean DEFAULT false,
    datestatus character varying(20),
    about text,
    bio text,
    reauthorized_at timestamp with time zone
);


ALTER TABLE public.accounts OWNER TO postgres;

--
-- Name: accounts_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.accounts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.accounts_id_seq OWNER TO postgres;

--
-- Name: accounts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.accounts_id_seq OWNED BY public.accounts.id;


--
-- Name: api_keys; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.api_keys (
    id integer NOT NULL,
    name character varying(100),
    api_id integer NOT NULL,
    api_hash character varying(255) NOT NULL,
    daily_limit integer DEFAULT 1000,
    requests_today integer DEFAULT 0,
    last_reset timestamp without time zone DEFAULT now()
);


ALTER TABLE public.api_keys OWNER TO postgres;

--
-- Name: api_keys_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.api_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.api_keys_id_seq OWNER TO postgres;

--
-- Name: api_keys_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.api_keys_id_seq OWNED BY public.api_keys.id;


--
-- Name: channels; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.channels (
    id integer NOT NULL,
    account_id integer,
    title text NOT NULL,
    username text,
    invite_link text,
    is_public boolean DEFAULT false,
    avatar_path text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.channels OWNER TO postgres;

--
-- Name: channels_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.channels_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.channels_id_seq OWNER TO postgres;

--
-- Name: channels_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.channels_id_seq OWNED BY public.channels.id;


--
-- Name: check_groups_log; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.check_groups_log (
    id integer NOT NULL,
    task_id integer NOT NULL,
    account_id integer,
    account_username text,
    checked_group text,
    result text,
    members integer,
    error_message text,
    checked_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.check_groups_log OWNER TO postgres;

--
-- Name: check_groups_log_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.check_groups_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.check_groups_log_id_seq OWNER TO postgres;

--
-- Name: check_groups_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.check_groups_log_id_seq OWNED BY public.check_groups_log.id;


--
-- Name: import_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.import_logs (
    id integer NOT NULL,
    "timestamp" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    username text,
    message text
);


ALTER TABLE public.import_logs OWNER TO postgres;

--
-- Name: import_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.import_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.import_logs_id_seq OWNER TO postgres;

--
-- Name: import_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.import_logs_id_seq OWNED BY public.import_logs.id;


--
-- Name: join_groups_log; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.join_groups_log (
    id integer NOT NULL,
    task_id integer NOT NULL,
    account_id integer NOT NULL,
    group_link text NOT NULL,
    status character varying(16) NOT NULL,
    message text,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.join_groups_log OWNER TO postgres;

--
-- Name: join_groups_log_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.join_groups_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.join_groups_log_id_seq OWNER TO postgres;

--
-- Name: join_groups_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.join_groups_log_id_seq OWNED BY public.join_groups_log.id;


--
-- Name: like_comments_log; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.like_comments_log (
    id integer NOT NULL,
    task_id integer NOT NULL,
    account_id integer NOT NULL,
    channel text NOT NULL,
    post_id bigint,
    comment_id bigint,
    reaction text,
    status text NOT NULL,
    message text,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.like_comments_log OWNER TO postgres;

--
-- Name: like_comments_log_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.like_comments_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.like_comments_log_id_seq OWNER TO postgres;

--
-- Name: like_comments_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.like_comments_log_id_seq OWNED BY public.like_comments_log.id;


--
-- Name: like_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.like_logs (
    id bigint NOT NULL,
    task_id integer NOT NULL,
    account_id integer,
    channel text,
    post_id bigint,
    comment_id bigint,
    reaction text,
    status text,
    error text,
    ts timestamp with time zone DEFAULT now()
);


ALTER TABLE public.like_logs OWNER TO postgres;

--
-- Name: like_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.like_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.like_logs_id_seq OWNER TO postgres;

--
-- Name: like_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.like_logs_id_seq OWNED BY public.like_logs.id;


--
-- Name: like_reactions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.like_reactions (
    id integer NOT NULL,
    task_id integer NOT NULL,
    account_id integer NOT NULL,
    channel_username text NOT NULL,
    post_id bigint NOT NULL,
    comment_id bigint NOT NULL,
    reacted_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.like_reactions OWNER TO postgres;

--
-- Name: like_reactions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.like_reactions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.like_reactions_id_seq OWNER TO postgres;

--
-- Name: like_reactions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.like_reactions_id_seq OWNED BY public.like_reactions.id;


--
-- Name: like_watch_state; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.like_watch_state (
    id integer NOT NULL,
    task_id integer NOT NULL,
    account_id integer NOT NULL,
    channel text NOT NULL,
    last_seen_post_id bigint DEFAULT 0,
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.like_watch_state OWNER TO postgres;

--
-- Name: like_watch_state_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.like_watch_state_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.like_watch_state_id_seq OWNER TO postgres;

--
-- Name: like_watch_state_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.like_watch_state_id_seq OWNED BY public.like_watch_state.id;


--
-- Name: log_settings; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.log_settings (
    id integer NOT NULL,
    retention_days integer DEFAULT 7,
    max_entries integer DEFAULT 5000
);


ALTER TABLE public.log_settings OWNER TO postgres;

--
-- Name: log_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.log_settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.log_settings_id_seq OWNER TO postgres;

--
-- Name: log_settings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.log_settings_id_seq OWNED BY public.log_settings.id;


--
-- Name: logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.logs (
    id integer NOT NULL,
    action text NOT NULL,
    task_id integer,
    "timestamp" timestamp without time zone DEFAULT now(),
    ip_address text,
    user_agent text,
    description text
);


ALTER TABLE public.logs OWNER TO postgres;

--
-- Name: logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.logs_id_seq OWNER TO postgres;

--
-- Name: logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.logs_id_seq OWNED BY public.logs.id;


--
-- Name: proxies; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.proxies (
    id integer NOT NULL,
    host character varying(255) NOT NULL,
    port integer NOT NULL,
    username character varying(255),
    password character varying(255),
    status character varying(50) DEFAULT 'unknown'::character varying,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.proxies OWNER TO postgres;

--
-- Name: proxies_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.proxies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.proxies_id_seq OWNER TO postgres;

--
-- Name: proxies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.proxies_id_seq OWNED BY public.proxies.id;


--
-- Name: search_groups_results; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.search_groups_results (
    id integer NOT NULL,
    task_id integer,
    user_id bigint,
    account_id integer,
    keyword text,
    group_id bigint,
    title text,
    username text,
    members integer,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.search_groups_results OWNER TO postgres;

--
-- Name: search_groups_results_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.search_groups_results_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.search_groups_results_id_seq OWNER TO postgres;

--
-- Name: search_groups_results_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.search_groups_results_id_seq OWNED BY public.search_groups_results.id;


--
-- Name: spambot_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.spambot_logs (
    id integer NOT NULL,
    account_id integer NOT NULL,
    "timestamp" timestamp without time zone NOT NULL,
    from_who character varying(16) NOT NULL,
    message text NOT NULL
);


ALTER TABLE public.spambot_logs OWNER TO postgres;

--
-- Name: spambot_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.spambot_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.spambot_logs_id_seq OWNER TO postgres;

--
-- Name: spambot_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.spambot_logs_id_seq OWNED BY public.spambot_logs.id;


--
-- Name: task_create; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.task_create (
    id integer NOT NULL,
    task_id integer,
    account_id integer,
    "timestamp" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    log_text text
);


ALTER TABLE public.task_create OWNER TO postgres;

--
-- Name: task_create_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.task_create_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.task_create_id_seq OWNER TO postgres;

--
-- Name: task_create_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.task_create_id_seq OWNED BY public.task_create.id;


--
-- Name: task_del; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.task_del (
    id integer NOT NULL,
    task_id integer,
    account_id integer,
    "timestamp" timestamp without time zone DEFAULT now(),
    log_text text NOT NULL
);


ALTER TABLE public.task_del OWNER TO postgres;

--
-- Name: task_del_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.task_del_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.task_del_id_seq OWNER TO postgres;

--
-- Name: task_del_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.task_del_id_seq OWNED BY public.task_del.id;


--
-- Name: task_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.task_logs (
    id integer NOT NULL,
    task_id integer NOT NULL,
    "timestamp" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    message text NOT NULL,
    status character varying(20) DEFAULT 'info'::character varying,
    duration double precision,
    account_id integer,
    proxy text
);


ALTER TABLE public.task_logs OWNER TO postgres;

--
-- Name: task_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.task_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.task_logs_id_seq OWNER TO postgres;

--
-- Name: task_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.task_logs_id_seq OWNED BY public.task_logs.id;


--
-- Name: task_results; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.task_results (
    task_id integer NOT NULL,
    result text
);


ALTER TABLE public.task_results OWNER TO postgres;

--
-- Name: tasks; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.tasks (
    id integer NOT NULL,
    account_id integer,
    type character varying(50) NOT NULL,
    payload jsonb,
    status character varying(20) DEFAULT 'pending'::character varying,
    result text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    scheduled_at timestamp with time zone DEFAULT now(),
    is_active boolean DEFAULT true,
    is_master boolean DEFAULT false,
    parent_id integer,
    task_type text,
    created_by bigint,
    accounts_count integer DEFAULT 0,
    finished_at timestamp without time zone,
    progress text
);


ALTER TABLE public.tasks OWNER TO postgres;

--
-- Name: tasks_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tasks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.tasks_id_seq OWNER TO postgres;

--
-- Name: tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tasks_id_seq OWNED BY public.tasks.id;


--
-- Name: twofa_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.twofa_logs (
    id integer NOT NULL,
    task_id integer NOT NULL,
    ts timestamp with time zone DEFAULT now() NOT NULL,
    account_id bigint,
    username text,
    ok boolean NOT NULL,
    removed_other boolean DEFAULT false NOT NULL,
    message text
);


ALTER TABLE public.twofa_logs OWNER TO postgres;

--
-- Name: twofa_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.twofa_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.twofa_logs_id_seq OWNER TO postgres;

--
-- Name: twofa_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.twofa_logs_id_seq OWNED BY public.twofa_logs.id;


--
-- Name: twofa_task_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.twofa_task_logs (
    id integer NOT NULL,
    task_id integer NOT NULL,
    ts timestamp without time zone DEFAULT now() NOT NULL,
    account_id integer,
    username text,
    ok boolean NOT NULL,
    removed_other boolean DEFAULT false NOT NULL,
    message text
);


ALTER TABLE public.twofa_task_logs OWNER TO postgres;

--
-- Name: twofa_task_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.twofa_task_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.twofa_task_logs_id_seq OWNER TO postgres;

--
-- Name: twofa_task_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.twofa_task_logs_id_seq OWNED BY public.twofa_task_logs.id;


--
-- Name: twofa_tasks; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.twofa_tasks (
    id integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    started_at timestamp without time zone,
    finished_at timestamp without time zone,
    user_id integer,
    mode character varying(16) NOT NULL,
    kill_other boolean DEFAULT false NOT NULL,
    status character varying(16) DEFAULT 'pending'::character varying NOT NULL,
    accounts_json jsonb NOT NULL,
    new_password text,
    old_password text
);


ALTER TABLE public.twofa_tasks OWNER TO postgres;

--
-- Name: twofa_tasks_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.twofa_tasks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.twofa_tasks_id_seq OWNER TO postgres;

--
-- Name: twofa_tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.twofa_tasks_id_seq OWNED BY public.twofa_tasks.id;


--
-- Name: account_groups id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.account_groups ALTER COLUMN id SET DEFAULT nextval('public.account_groups_id_seq'::regclass);


--
-- Name: account_session_history id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.account_session_history ALTER COLUMN id SET DEFAULT nextval('public.account_session_history_id_seq'::regclass);


--
-- Name: accounts id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.accounts ALTER COLUMN id SET DEFAULT nextval('public.accounts_id_seq'::regclass);


--
-- Name: api_keys id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.api_keys ALTER COLUMN id SET DEFAULT nextval('public.api_keys_id_seq'::regclass);


--
-- Name: channels id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.channels ALTER COLUMN id SET DEFAULT nextval('public.channels_id_seq'::regclass);


--
-- Name: check_groups_log id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.check_groups_log ALTER COLUMN id SET DEFAULT nextval('public.check_groups_log_id_seq'::regclass);


--
-- Name: import_logs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.import_logs ALTER COLUMN id SET DEFAULT nextval('public.import_logs_id_seq'::regclass);


--
-- Name: join_groups_log id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.join_groups_log ALTER COLUMN id SET DEFAULT nextval('public.join_groups_log_id_seq'::regclass);


--
-- Name: like_comments_log id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.like_comments_log ALTER COLUMN id SET DEFAULT nextval('public.like_comments_log_id_seq'::regclass);


--
-- Name: like_logs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.like_logs ALTER COLUMN id SET DEFAULT nextval('public.like_logs_id_seq'::regclass);


--
-- Name: like_reactions id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.like_reactions ALTER COLUMN id SET DEFAULT nextval('public.like_reactions_id_seq'::regclass);


--
-- Name: like_watch_state id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.like_watch_state ALTER COLUMN id SET DEFAULT nextval('public.like_watch_state_id_seq'::regclass);


--
-- Name: log_settings id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.log_settings ALTER COLUMN id SET DEFAULT nextval('public.log_settings_id_seq'::regclass);


--
-- Name: logs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.logs ALTER COLUMN id SET DEFAULT nextval('public.logs_id_seq'::regclass);


--
-- Name: proxies id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.proxies ALTER COLUMN id SET DEFAULT nextval('public.proxies_id_seq'::regclass);


--
-- Name: search_groups_results id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.search_groups_results ALTER COLUMN id SET DEFAULT nextval('public.search_groups_results_id_seq'::regclass);


--
-- Name: spambot_logs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.spambot_logs ALTER COLUMN id SET DEFAULT nextval('public.spambot_logs_id_seq'::regclass);


--
-- Name: task_create id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_create ALTER COLUMN id SET DEFAULT nextval('public.task_create_id_seq'::regclass);


--
-- Name: task_del id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_del ALTER COLUMN id SET DEFAULT nextval('public.task_del_id_seq'::regclass);


--
-- Name: task_logs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_logs ALTER COLUMN id SET DEFAULT nextval('public.task_logs_id_seq'::regclass);


--
-- Name: tasks id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tasks ALTER COLUMN id SET DEFAULT nextval('public.tasks_id_seq'::regclass);


--
-- Name: twofa_logs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.twofa_logs ALTER COLUMN id SET DEFAULT nextval('public.twofa_logs_id_seq'::regclass);


--
-- Name: twofa_task_logs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.twofa_task_logs ALTER COLUMN id SET DEFAULT nextval('public.twofa_task_logs_id_seq'::regclass);


--
-- Name: twofa_tasks id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.twofa_tasks ALTER COLUMN id SET DEFAULT nextval('public.twofa_tasks_id_seq'::regclass);


--
-- Name: account_groups account_groups_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.account_groups
    ADD CONSTRAINT account_groups_name_key UNIQUE (name);


--
-- Name: account_groups account_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.account_groups
    ADD CONSTRAINT account_groups_pkey PRIMARY KEY (id);


--
-- Name: account_session_history account_session_history_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.account_session_history
    ADD CONSTRAINT account_session_history_pkey PRIMARY KEY (id);


--
-- Name: accounts accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_pkey PRIMARY KEY (id);


--
-- Name: api_keys api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);


--
-- Name: channels channels_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.channels
    ADD CONSTRAINT channels_pkey PRIMARY KEY (id);


--
-- Name: check_groups_log check_groups_log_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.check_groups_log
    ADD CONSTRAINT check_groups_log_pkey PRIMARY KEY (id);


--
-- Name: import_logs import_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.import_logs
    ADD CONSTRAINT import_logs_pkey PRIMARY KEY (id);


--
-- Name: join_groups_log join_groups_log_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.join_groups_log
    ADD CONSTRAINT join_groups_log_pkey PRIMARY KEY (id);


--
-- Name: like_comments_log like_comments_log_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.like_comments_log
    ADD CONSTRAINT like_comments_log_pkey PRIMARY KEY (id);


--
-- Name: like_logs like_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.like_logs
    ADD CONSTRAINT like_logs_pkey PRIMARY KEY (id);


--
-- Name: like_reactions like_reactions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.like_reactions
    ADD CONSTRAINT like_reactions_pkey PRIMARY KEY (id);


--
-- Name: like_reactions like_reactions_task_id_account_id_channel_username_post_id__key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.like_reactions
    ADD CONSTRAINT like_reactions_task_id_account_id_channel_username_post_id__key UNIQUE (task_id, account_id, channel_username, post_id, comment_id);


--
-- Name: like_watch_state like_watch_state_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.like_watch_state
    ADD CONSTRAINT like_watch_state_pkey PRIMARY KEY (id);


--
-- Name: like_watch_state like_watch_state_task_id_account_id_channel_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.like_watch_state
    ADD CONSTRAINT like_watch_state_task_id_account_id_channel_key UNIQUE (task_id, account_id, channel);


--
-- Name: log_settings log_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.log_settings
    ADD CONSTRAINT log_settings_pkey PRIMARY KEY (id);


--
-- Name: logs logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.logs
    ADD CONSTRAINT logs_pkey PRIMARY KEY (id);


--
-- Name: proxies proxies_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.proxies
    ADD CONSTRAINT proxies_pkey PRIMARY KEY (id);


--
-- Name: search_groups_results search_groups_results_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.search_groups_results
    ADD CONSTRAINT search_groups_results_pkey PRIMARY KEY (id);


--
-- Name: spambot_logs spambot_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.spambot_logs
    ADD CONSTRAINT spambot_logs_pkey PRIMARY KEY (id);


--
-- Name: task_create task_create_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_create
    ADD CONSTRAINT task_create_pkey PRIMARY KEY (id);


--
-- Name: task_del task_del_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_del
    ADD CONSTRAINT task_del_pkey PRIMARY KEY (id);


--
-- Name: task_logs task_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_logs
    ADD CONSTRAINT task_logs_pkey PRIMARY KEY (id);


--
-- Name: task_results task_results_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_results
    ADD CONSTRAINT task_results_pkey PRIMARY KEY (task_id);


--
-- Name: tasks tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);


--
-- Name: twofa_logs twofa_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.twofa_logs
    ADD CONSTRAINT twofa_logs_pkey PRIMARY KEY (id);


--
-- Name: twofa_task_logs twofa_task_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.twofa_task_logs
    ADD CONSTRAINT twofa_task_logs_pkey PRIMARY KEY (id);


--
-- Name: twofa_tasks twofa_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.twofa_tasks
    ADD CONSTRAINT twofa_tasks_pkey PRIMARY KEY (id);


--
-- Name: idx_check_groups_log_account_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_check_groups_log_account_id ON public.check_groups_log USING btree (account_id);


--
-- Name: idx_check_groups_log_task_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_check_groups_log_task_id ON public.check_groups_log USING btree (task_id);


--
-- Name: idx_like_log_acc_msg; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_like_log_acc_msg ON public.like_comments_log USING btree (account_id, comment_id);


--
-- Name: idx_like_log_task; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_like_log_task ON public.like_comments_log USING btree (task_id);


--
-- Name: idx_like_logs_acc; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_like_logs_acc ON public.like_logs USING btree (account_id);


--
-- Name: idx_like_logs_stat; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_like_logs_stat ON public.like_logs USING btree (status);


--
-- Name: idx_like_logs_task; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_like_logs_task ON public.like_logs USING btree (task_id);


--
-- Name: idx_task_logs_task_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_task_logs_task_id ON public.task_logs USING btree (task_id);


--
-- Name: idx_twofa_logs_task_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_twofa_logs_task_id ON public.twofa_logs USING btree (task_id);


--
-- Name: idx_twofa_task_logs_task_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_twofa_task_logs_task_id ON public.twofa_task_logs USING btree (task_id);


--
-- Name: idx_twofa_tasks_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_twofa_tasks_status ON public.twofa_tasks USING btree (status);


--
-- Name: accounts accounts_api_key_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_api_key_id_fkey FOREIGN KEY (api_key_id) REFERENCES public.api_keys(id);


--
-- Name: accounts accounts_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_group_id_fkey FOREIGN KEY (group_id) REFERENCES public.account_groups(id);


--
-- Name: channels channels_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.channels
    ADD CONSTRAINT channels_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(id) ON DELETE CASCADE;


--
-- Name: task_logs fk_task; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_logs
    ADD CONSTRAINT fk_task FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: task_del task_del_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_del
    ADD CONSTRAINT task_del_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(id) ON DELETE CASCADE;


--
-- Name: task_del task_del_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_del
    ADD CONSTRAINT task_del_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: task_results task_results_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_results
    ADD CONSTRAINT task_results_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: tasks tasks_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(id);


--
-- Name: tasks tasks_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: twofa_logs twofa_logs_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.twofa_logs
    ADD CONSTRAINT twofa_logs_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.twofa_tasks(id) ON DELETE CASCADE;


--
-- Name: twofa_task_logs twofa_task_logs_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.twofa_task_logs
    ADD CONSTRAINT twofa_task_logs_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.twofa_tasks(id) ON DELETE CASCADE;


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: postgres
--

GRANT ALL ON SCHEMA public TO tguser;


--
-- Name: TABLE account_groups; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.account_groups TO tguser;


--
-- Name: SEQUENCE account_groups_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.account_groups_id_seq TO tguser;


--
-- Name: TABLE account_session_history; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.account_session_history TO tguser;


--
-- Name: SEQUENCE account_session_history_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.account_session_history_id_seq TO tguser;


--
-- Name: TABLE accounts; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.accounts TO tguser;


--
-- Name: SEQUENCE accounts_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.accounts_id_seq TO tguser;


--
-- Name: TABLE api_keys; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.api_keys TO tguser;


--
-- Name: SEQUENCE api_keys_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.api_keys_id_seq TO tguser;


--
-- Name: TABLE channels; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.channels TO tguser;


--
-- Name: SEQUENCE channels_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.channels_id_seq TO tguser;


--
-- Name: TABLE check_groups_log; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.check_groups_log TO tguser;


--
-- Name: SEQUENCE check_groups_log_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.check_groups_log_id_seq TO tguser;


--
-- Name: TABLE import_logs; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.import_logs TO tguser;


--
-- Name: SEQUENCE import_logs_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.import_logs_id_seq TO tguser;


--
-- Name: TABLE join_groups_log; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.join_groups_log TO tguser;


--
-- Name: SEQUENCE join_groups_log_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.join_groups_log_id_seq TO tguser;


--
-- Name: TABLE like_comments_log; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.like_comments_log TO tguser;


--
-- Name: SEQUENCE like_comments_log_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.like_comments_log_id_seq TO tguser;


--
-- Name: TABLE like_logs; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.like_logs TO tguser;


--
-- Name: SEQUENCE like_logs_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.like_logs_id_seq TO tguser;


--
-- Name: TABLE like_reactions; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.like_reactions TO tguser;


--
-- Name: SEQUENCE like_reactions_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.like_reactions_id_seq TO tguser;


--
-- Name: TABLE like_watch_state; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.like_watch_state TO tguser;


--
-- Name: SEQUENCE like_watch_state_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.like_watch_state_id_seq TO tguser;


--
-- Name: TABLE log_settings; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.log_settings TO tguser;


--
-- Name: SEQUENCE log_settings_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.log_settings_id_seq TO tguser;


--
-- Name: TABLE logs; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.logs TO tguser;


--
-- Name: SEQUENCE logs_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.logs_id_seq TO tguser;


--
-- Name: TABLE proxies; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.proxies TO tguser;


--
-- Name: SEQUENCE proxies_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.proxies_id_seq TO tguser;


--
-- Name: TABLE search_groups_results; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.search_groups_results TO tguser;


--
-- Name: SEQUENCE search_groups_results_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.search_groups_results_id_seq TO tguser;


--
-- Name: TABLE spambot_logs; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.spambot_logs TO tguser;


--
-- Name: SEQUENCE spambot_logs_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.spambot_logs_id_seq TO tguser;


--
-- Name: TABLE task_create; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.task_create TO tguser;


--
-- Name: SEQUENCE task_create_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.task_create_id_seq TO tguser;


--
-- Name: TABLE task_del; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.task_del TO tguser;


--
-- Name: SEQUENCE task_del_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.task_del_id_seq TO tguser;


--
-- Name: TABLE task_logs; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.task_logs TO tguser;


--
-- Name: SEQUENCE task_logs_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.task_logs_id_seq TO tguser;


--
-- Name: TABLE task_results; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.task_results TO tguser;


--
-- Name: TABLE tasks; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.tasks TO tguser;


--
-- Name: SEQUENCE tasks_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.tasks_id_seq TO tguser;


--
-- Name: TABLE twofa_logs; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.twofa_logs TO tguser;


--
-- Name: SEQUENCE twofa_logs_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.twofa_logs_id_seq TO tguser;


--
-- Name: TABLE twofa_task_logs; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.twofa_task_logs TO tguser;


--
-- Name: SEQUENCE twofa_task_logs_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.twofa_task_logs_id_seq TO tguser;


--
-- Name: TABLE twofa_tasks; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.twofa_tasks TO tguser;


--
-- Name: SEQUENCE twofa_tasks_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.twofa_tasks_id_seq TO tguser;


--
-- Name: DEFAULT PRIVILEGES FOR SEQUENCES; Type: DEFAULT ACL; Schema: public; Owner: postgres
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES  TO tguser;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: postgres
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT,INSERT,DELETE,UPDATE ON TABLES  TO tguser;


--
-- PostgreSQL database dump complete
--

\unrestrict y9GQXw9JCD2ZFc8a0fzWbKpInWCoWyIv9ChvDlN2pyGAy85FR84534Vk7dPLFop

