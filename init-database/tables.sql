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
