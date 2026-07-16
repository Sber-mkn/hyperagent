create table users(
    id serial primary key,
    login varchar(100) unique not null,
    password_hash varchar(255) not null,
    db_port int not null,
    rabbitmq_port int not null,
    rabbitmq_mgmt_port int not null
);