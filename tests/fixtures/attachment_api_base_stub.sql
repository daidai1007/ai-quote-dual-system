-- Synthetic PRODUCT calculators only, for exercising the real HTTP -> psql path.
-- Attachment tables, imported rules and snapshots are the real migration code.
CREATE TABLE calc.material(material_code varchar PRIMARY KEY,density_g_cm3 numeric);
INSERT INTO calc.material VALUES('SECC',7.85),('SUS304',7.93),('SUS316',7.98);
CREATE FUNCTION calc.get_material_unit_price(varchar,date) RETURNS numeric LANGUAGE sql AS 'SELECT 5::numeric';
CREATE FUNCTION calc.get_spray_unit_price(date,varchar) RETURNS numeric LANGUAGE sql AS 'SELECT 10::numeric';
CREATE TABLE calc.local_base_probe(quote_id text);
CREATE TABLE calc.quick_quote_experience(quick_rule_id bigint,product_code text,model_code text,material_code text,
 reference_width_mm numeric,reference_height_mm numeric,reference_depth_mm numeric,quick_base_price numeric,
 source_file text,source_sheet text,source_row_no integer);
INSERT INTO calc.quick_quote_experience VALUES(1,'JP','','SECC',800,2000,600,200,'LOCAL','LOCAL',1);
CREATE FUNCTION calc.match_quick_quote(text,text,text,numeric,numeric,numeric,date)
RETURNS TABLE(quick_rule_id bigint,quick_total_cost numeric,match_method text,dimension_distance numeric)
LANGUAGE sql AS $$ SELECT 1::bigint,200::numeric,'LOCAL'::text,0::numeric $$;
CREATE FUNCTION calc.calculate_dual_quote(text,text,text,text,numeric,numeric,numeric,numeric,numeric,text,text,date)
RETURNS TABLE(quote_id text,formula_material_cost numeric,formula_auxiliary_cost numeric,formula_labor_cost numeric,
 formula_attachment_fee numeric,formula_product_area_m2 numeric,formula_spray_cost numeric,formula_management_fee numeric,
 formula_total_cost numeric,quick_attachment_fee numeric,risk_flags jsonb)
LANGUAGE plpgsql AS $$ BEGIN
  INSERT INTO calc.local_base_probe VALUES($1);
  RETURN QUERY SELECT $1,78.7::numeric,5::numeric,10::numeric,0::numeric,2::numeric,5::numeric,1.3::numeric,100::numeric,0::numeric,'[]'::jsonb;
END $$;
CREATE TABLE calc.ordering_company(company_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 company_code text UNIQUE,company_name text,contact_name text,contact_phone text,company_address text,is_active boolean);
CREATE TABLE calc.quote_document(quote_id text PRIMARY KEY,company_id bigint,quote_date date,status text,document_payload jsonb);
CREATE TABLE calc.company_quote_history(history_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 company_id bigint,quote_id text,product_code text,model_code text,material_code text,coating_type text,variant_code text,
 width_mm numeric,height_mm numeric,depth_mm numeric,request_payload jsonb,created_at timestamptz DEFAULT now());
