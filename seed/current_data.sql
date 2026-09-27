-- Snapshot of the current production data, loaded when the orders table is still empty.
INSERT INTO orders(order_no,customer_email,amount_jpy,status,created_at,updated_at) VALUES
  ('ord-20260802-6336','customer001@example.com',1700,'paid','2026-08-02T04:00:00Z','2026-08-02T04:00:00Z'),
  ('ord-20260805-5436','ken@example.com',42000,'pending','2026-08-05T04:20:00Z','2026-08-05T04:20:00Z'),
  ('ord-20260807-4277','kaede@example.com',24000,'paid','2026-08-07T11:00:00Z','2026-08-08T11:00:00Z'),
  ('ord-20260809-6327','mei@example.com',33000,'failed','2026-08-09T06:00:00Z','2026-08-09T06:00:21Z'),
  ('ord-20260811-7307','rin@example.com',7000,'paid','2026-08-11T08:00:00Z','2026-08-11T09:30:00Z'),
  ('ord-20260813-1435','customer002@example.com',5900,'refunded','2026-08-13T05:00:00Z','2026-08-17T05:00:00Z'),
  ('ord-20260814-4634','haru@example.com',51000,'pending','2026-08-14T09:05:00Z','2026-08-14T09:05:00Z'),
  ('ord-20260816-7485','eri@example.com',11000,'failed','2026-08-16T20:15:00Z','2026-08-16T20:15:00Z'),
  ('ord-20260818-2317','yui@example.com',36000,'paid','2026-08-18T05:00:00Z','2026-08-18T05:00:00Z'),
  ('ord-20260820-3297','sho@example.com',9000,'refunded','2026-08-20T01:00:00Z','2026-08-24T02:00:00Z'),
  ('ord-20260822-9535','nao@example.com',2600,'pending','2026-08-22T13:20:00Z','2026-08-22T13:20:00Z'),
  ('ord-20260824-8376','itsuki@example.com',20000,'paid','2026-08-24T16:20:00Z','2026-08-26T16:20:00Z'),
  ('ord-20260826-1426','sora@example.com',38000,'failed','2026-08-26T07:30:00Z','2026-08-26T07:30:30Z'),
  ('ord-20260827-5534','customer003@example.com',2400,'paid','2026-08-27T06:00:00Z','2026-08-27T06:00:00Z'),
  ('ord-20260829-3386','toma@example.com',6400,'pending','2026-08-29T15:40:00Z','2026-08-29T15:40:00Z');

INSERT INTO charges(order_id,provider_charge_id,amount_jpy,status,attempts,last_error,created_at,updated_at) VALUES
  ((SELECT id FROM orders WHERE order_no='ord-20260802-6336'),'ch_0000000000000000000000b1',1700,'succeeded',1,'','2026-08-02T04:00:00Z','2026-08-02T04:00:00Z'),
  ((SELECT id FROM orders WHERE order_no='ord-20260805-5436'),'',42000,'unknown',1,'paylink: HTTPConnectionPool(host=''127.0.0.1'', port=9900): Read timed out. (read timeout=3)','2026-08-05T04:20:00Z','2026-08-05T04:20:00Z'),
  ((SELECT id FROM orders WHERE order_no='ord-20260807-4277'),'ch_000000000000000000000r1a',24000,'succeeded',1,'','2026-08-07T11:00:00Z','2026-08-07T11:00:00Z'),
  ((SELECT id FROM orders WHERE order_no='ord-20260807-4277'),'ch_000000000000000000000r1b',24000,'refunded',1,'','2026-08-07T11:00:08Z','2026-08-08T11:00:00Z'),
  ((SELECT id FROM orders WHERE order_no='ord-20260809-6327'),'',33000,'failed',3,'paylink: HTTPConnectionPool(host=''127.0.0.1'', port=9900): Read timed out. (read timeout=3)','2026-08-09T06:00:00Z','2026-08-09T06:00:21Z'),
  ((SELECT id FROM orders WHERE order_no='ord-20260813-1435'),'ch_0000000000000000000000b2',5900,'refunded',1,'','2026-08-13T05:00:00Z','2026-08-17T05:00:00Z'),
  ((SELECT id FROM orders WHERE order_no='ord-20260814-4634'),'',51000,'unknown',1,'paylink: HTTPConnectionPool(host=''127.0.0.1'', port=9900): Read timed out. (read timeout=3)','2026-08-14T09:05:00Z','2026-08-14T09:05:00Z'),
  ((SELECT id FROM orders WHERE order_no='ord-20260816-7485'),'ch_0000000000000000000000f3',11000,'failed',1,'','2026-08-16T20:15:00Z','2026-08-16T20:15:00Z'),
  ((SELECT id FROM orders WHERE order_no='ord-20260818-2317'),'ch_0000000000000000000000p1',36000,'succeeded',1,'','2026-08-18T05:00:00Z','2026-08-18T05:00:00Z'),
  ((SELECT id FROM orders WHERE order_no='ord-20260820-3297'),'ch_0000000000000000000000o1',9000,'refunded',1,'','2026-08-20T01:00:00Z','2026-08-24T02:00:00Z'),
  ((SELECT id FROM orders WHERE order_no='ord-20260822-9535'),'',2600,'unknown',1,'paylink: HTTPConnectionPool(host=''127.0.0.1'', port=9900): Read timed out. (read timeout=3)','2026-08-22T13:20:00Z','2026-08-22T13:20:00Z'),
  ((SELECT id FROM orders WHERE order_no='ord-20260824-8376'),'ch_0000000000000000000000r2',20000,'succeeded',1,'','2026-08-24T16:20:00Z','2026-08-26T16:20:00Z'),
  ((SELECT id FROM orders WHERE order_no='ord-20260826-1426'),'',38000,'failed',3,'paylink: HTTPConnectionPool(host=''127.0.0.1'', port=9900): Read timed out. (read timeout=3)','2026-08-26T07:30:00Z','2026-08-26T07:30:30Z'),
  ((SELECT id FROM orders WHERE order_no='ord-20260827-5534'),'ch_0000000000000000000000b3',2400,'succeeded',1,'','2026-08-27T06:00:00Z','2026-08-27T06:00:00Z'),
  ((SELECT id FROM orders WHERE order_no='ord-20260829-3386'),'ch_0000000000000000000000f2',6400,'unknown',1,'','2026-08-29T15:40:00Z','2026-08-29T15:40:00Z');
