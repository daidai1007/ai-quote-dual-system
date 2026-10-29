-- Pure rank checks and definition markers, no quote creation or repricing.
SELECT calc.experience_dimension_rank(600,1900,100,600,1600,400) AS nearer_3d_but_larger_area_difference,
       calc.experience_dimension_rank(600,1000,1000,600,1600,400) AS selected_by_surface_area;
SELECT count(*)>=5 AS required_matchers_recorded,
       bool_and(coalesce(md5(pg_get_functiondef(to_regprocedure(function_identity)))=patched_definition_md5,false)) AS installed_definitions_match
FROM calc.experience_dimension_match_backup WHERE migration_key='width-perimeter-area-20261028-v1';
