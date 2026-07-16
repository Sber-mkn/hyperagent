create table snapshots
(
    id            serial primary key,
    sha           varchar(40) not null,
    status        varchar(20) not null,
    snapshot_time timestamp default current_timestamp,
    modification  text        not null
    constraint check_status
    check (status in ('PENDING', 'STABLE', 'ERROR'))
);

create table errors
(
    id          serial primary key,
    snapshot_id int4 not null,
    error_text  text not null,
    error_time  timestamp default current_timestamp,
    constraint fk_snapshot foreign key (snapshot_id)
        references snapshots (id)
        on update cascade
        on delete cascade
);

create table llmchat
(
    id serial primary key,
    chat_id int not null,
    done boolean not null default true,
    done_reason text default null,
    role varchar(10) not null,
    thinking text not null default '',
    content text not null default '',
    tool_calls jsonb default null,
    tool_call_id varchar(255) default null,
    provider varchar(255) not null default '',
    model varchar(255) not null default '',
    tokens_prompt int default null,
    tokens_response int default null,
    duration_load int default null,
    duration_prompt int default null,
    duration_response int default null,
    dt timestamp default current_timestamp,
    constraint check_role
    check (role in ('assistant', 'system', 'user', 'tool'))
);

create table l3_memory
(
    chat_id int primary key,
    summary text not null,
    created_at timestamp default current_timestamp,
    last_message_id int not null
);

create user agent with password '12345';
grant usage on schema public to agent;
grant select, insert, update, delete on table llmchat to agent;
grant select, insert, update, delete on table l3_memory to agent;
grant usage, select on all sequences in schema public to agent;
