-- PostgreSQL schema for LightningTracker.WebApi

create table if not exists service_takers (
  id serial primary key,
  name text not null,
  lat double precision not null,
  lon double precision not null
);

create unique index if not exists ux_service_takers_name on service_takers(name);
