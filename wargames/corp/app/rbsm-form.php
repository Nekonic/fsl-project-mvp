<?php

global $wpdb;

$title = 'Community Submission';
$form_id = (int) $wpdb->get_var( $wpdb->prepare( "SELECT id FROM {$wpdb->prefix}rb_submission WHERE title = %s", $title ) );

if ( ! $form_id ) {
	$wpdb->insert(
		$wpdb->prefix . 'rb_submission',
		array(
			'title' => $title,
			'data'  => wp_json_encode(
				array(
					'general_setting' => array(
						'post_status'      => 'publish',
						'url_direction'    => '',
						'unique_title'     => true,
						'form_layout_type' => '2_cols',
					),
					'user_login'       => array(
						'author_access'    => 'allow_guest',
						'assign_author'    => '',
						'assign_author_id' => '1',
						'login_link_url'   => '',
						'login_type'       => array(
							'type'                       => 'show_login_message',
							'login_message'              => '',
							'login_link_label'           => '',
							'required_login_title'       => '',
							'required_login_title_desc'  => '',
							'register_link'              => '',
							'register_button_label'      => '',
						),
					),
					'form_fields'      => array(
						'user_name'      => 'require',
						'user_email'     => 'require',
						'post_title'     => 'require',
						'tagline'        => 'require',
						'editor_type'    => 'rich_editor',
						'max_images'     => 3,
						'max_image_size' => 100,
						'featured_image' => array(
							'status'                 => 'disable',
							'upload_file_size_limit' => 0,
							'default_featured_image' => '',
						),
						'categories'     => array(
							'multiple_categories'      => true,
							'exclude_categories'       => array(),
							'exclude_category_ids'     => array(),
							'auto_assign_categories'   => array(),
							'auto_assign_category_ids' => array(),
						),
						'tags'           => array(
							'multiple_tags'       => true,
							'allow_add_new_tag'   => true,
							'exclude_tags'        => array(),
							'exclude_tag_ids'     => array(),
							'auto_assign_tags'    => array(),
							'auto_assign_tag_ids' => array(),
						),
						'custom_field'   => array(),
					),
					'security_fields'  => array(
						'challenge' => array(
							'status'   => false,
							'question' => '',
							'response' => '',
						),
						'recaptcha' => array(
							'status'               => false,
							'recaptcha_site_key'   => '',
							'recaptcha_secret_key' => '',
						),
					),
					'email'            => array(
						'admin_mail'                 => array(
							'status'  => false,
							'email'   => '',
							'subject' => '',
							'title'   => '',
							'message' => '',
						),
						'post_submit_notification'   => array(
							'status'  => false,
							'subject' => '',
							'title'   => '',
							'message' => '',
						),
						'post_publish_notification'  => array(
							'status'  => false,
							'subject' => '',
							'title'   => '',
							'message' => '',
						),
						'post_trash_notification'    => array(
							'status'  => false,
							'subject' => '',
							'title'   => '',
							'message' => '',
						),
					),
				)
			),
		)
	);

	$form_id = (int) $wpdb->insert_id;
}

if ( null === get_page_by_path( 'submit-a-story' ) ) {
	wp_insert_post(
		array(
			'post_type'    => 'page',
			'post_title'   => 'Submit a Story',
			'post_name'    => 'submit-a-story',
			'post_status'  => 'publish',
			'post_author'  => 1,
			'post_content' => '[easy_post_submission_form id="' . $form_id . '"]',
		)
	);
}
