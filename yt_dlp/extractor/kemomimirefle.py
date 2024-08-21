import json

from .common import InfoExtractor
from ..utils import (
    ExtractorError,
    int_or_none,
    str_or_none,
    traverse_obj,
    unified_timestamp,
    url_or_none,
)


class KemomimirefleBaseIE(InfoExtractor):
    def _call_api(self, path, item_id, **kwargs):
        return self._download_json(
            f'https://api.kemomimirefle.net/fc/{path}', video_id=item_id, **kwargs)

    def _find_fanclub_site_id(self):
        # https://kemomimirefle.net/site/settings.json
        # "fanclub_site_id": "243",
        # "channel": false,
        # Hardcode id, should not change but if does, fetch from settings.json
        return 243

    def _get_channel_base_info(self, fanclub_site_id):
        return traverse_obj(self._call_api(
            f'fanclub_sites/{fanclub_site_id}/page_base_info', item_id=f'fanclub_sites/{fanclub_site_id}',
            note='Fetching channel base info', errnote='Unable to fetch channel base info', fatal=False,
        ), ('data', 'fanclub_site', {dict})) or {}

    def _get_channel_user_info(self, fanclub_site_id):
        return traverse_obj(self._call_api(
            f'fanclub_sites/{fanclub_site_id}/user_info', item_id=f'fanclub_sites/{fanclub_site_id}',
            note='Fetching channel user info', errnote='Unable to fetch channel user info', fatal=False,
            data=json.dumps('null').encode('ascii'),
        ), ('data', 'fanclub_site', {dict})) or {}


class KemomimirefleIE(KemomimirefleBaseIE):
    _VALID_URL = r'https?://(?:www\.)?kemomimirefle\.net/(?:video|live)/(?P<id>sm\w+)'
    _TESTS = [{
        'url': 'https://kemomimirefle.net/video/smCsZkEdgZ7yX4qEbaJ3sBb9',
        'md5': 'c91a74bf925656e3d3e650ab65b836fd',
        'info_dict': {
            'id': 'smCsZkEdgZ7yX4qEbaJ3sBb9',
            'ext': 'mp4',
            'title': '【全編無料】ビンビン元気回復♡下半身に響く耳舐めASMR♡【猫羽かりん】',
            'channel': 'けもみみりふれっ！出張所',
            'live_status': 'was_live',
            'thumbnail': 'https://kemomimirefle.net/public_html/contents/video_pages/35810/thumbnail_path?time=1722608703',
            'description': 'md5:7d3325ee6983572d01fab944af37c802',
            'timestamp': 1722608702,
            'duration': 5191,
            'comment_count': int,
            'view_count': int,
            'tags': 'count:2',
            'upload_date': '20240802',
            'age_limit': 15,
            'release_timestamp': 1722610800,
            'release_date': '20240802',
        },
    }]

    def _real_extract(self, url):
        content_code = self._match_id(url)
        fanclub_site_id = self._find_fanclub_site_id()

        data_json = self._call_api(
            f'video_pages/{content_code}', item_id=content_code, headers={'Fc_use_device': 'null'},
            note='Fetching video page info', errnote='Unable to fetch video page info',
        )['data']['video_page']

        live_status, session_id = self._get_live_status_and_session_id(content_code, data_json)

        release_timestamp_str = data_json.get('live_scheduled_start_at')

        formats = []

        if live_status == 'is_upcoming':
            if release_timestamp_str:
                msg = f'This live event will begin at {release_timestamp_str} UTC'
            else:
                msg = 'This event has not started yet'
            self.raise_no_formats(msg, expected=True, video_id=content_code)
        else:
            formats = self._extract_m3u8_formats(
                # "authenticated_url" is a format string that contains "{session_id}".
                m3u8_url=data_json['video_stream']['authenticated_url'].format(session_id=session_id),
                video_id=content_code)

        return {
            'id': content_code,
            'formats': formats,
            '_format_sort_fields': ('tbr', 'vcodec', 'acodec'),
            'channel': self._get_channel_base_info(fanclub_site_id).get('fanclub_site_name'),
            'age_limit': traverse_obj(self._get_channel_user_info(fanclub_site_id), ('content_provider', 'age_limit')),
            'live_status': live_status,
            'release_timestamp': unified_timestamp(release_timestamp_str),
            **traverse_obj(data_json, {
                'title': ('title', {str}),
                'thumbnail': ('thumbnail_url', {url_or_none}),
                'description': ('description', {str}),
                'timestamp': ('released_at', {unified_timestamp}),
                'duration': ('active_video_filename', 'length', {int_or_none}),
                'comment_count': ('video_aggregate_info', 'number_of_comments', {int_or_none}),
                'view_count': ('video_aggregate_info', 'total_views', {int_or_none}),
                'tags': ('video_tags', ..., 'tag', {str}),
            }),
            '__post_extractor': self.extract_comments(
                content_code=content_code,
                comment_group_id=traverse_obj(data_json, ('video_comment_setting', 'comment_group_id'))),
        }

    def _get_comments(self, content_code, comment_group_id):
        item_id = f'{content_code}/comments'

        if not comment_group_id:
            return None

        comment_access_token = self._call_api(
            f'video_pages/{content_code}/comments_user_token', item_id,
            note='Getting comment token', errnote='Unable to get comment token',
        )['data']['access_token']

        comment_list = self._download_json(
            'https://comm-api.sheeta.com/messages.history', video_id=item_id,
            note='Fetching comments', errnote='Unable to fetch comments',
            headers={'Content-Type': 'application/json'},
            query={
                'sort_direction': 'asc',
                'limit': int_or_none(self._configuration_arg('max_comments', [''])[0]) or 120,
            },
            data=json.dumps({
                'token': comment_access_token,
                'group_id': comment_group_id,
            }).encode('ascii'))

        for comment in traverse_obj(comment_list, ...):
            yield traverse_obj(comment, {
                'author': ('nickname', {str}),
                'author_id': ('sender_id', {str_or_none}),
                'id': ('id', {str_or_none}),
                'text': ('message', {str}),
                'timestamp': (('updated_at', 'sent_at', 'created_at'), {unified_timestamp}),
                'author_is_uploader': ('sender_id', {lambda x: x == '-1'}),
            }, get_all=False)

    def _get_live_status_and_session_id(self, content_code, data_json):
        video_type = data_json.get('type')
        live_finished_at = data_json.get('live_finished_at')

        payload = {}
        if video_type == 'vod':
            if live_finished_at:
                live_status = 'was_live'
            else:
                live_status = 'not_live'
        elif video_type == 'live':
            if not data_json.get('live_started_at'):
                return 'is_upcoming', ''

            if not live_finished_at:
                live_status = 'is_live'
            else:
                live_status = 'was_live'
                payload = {'broadcast_type': 'dvr'}

                video_allow_dvr_flg = traverse_obj(data_json, ('video', 'allow_dvr_flg'))
                video_convert_to_vod_flg = traverse_obj(data_json, ('video', 'convert_to_vod_flg'))

                self.write_debug(f'allow_dvr_flg = {video_allow_dvr_flg}, convert_to_vod_flg = {video_convert_to_vod_flg}.')

                if not (video_allow_dvr_flg and video_convert_to_vod_flg):
                    raise ExtractorError(
                        'Live was ended, there is no video for download.', video_id=content_code, expected=True)
        else:
            raise ExtractorError(f'Unknown type: {video_type}', video_id=content_code, expected=False)

        self.write_debug(f'{content_code}: video_type={video_type}, live_status={live_status}')

        session_id = self._call_api(
            f'video_pages/{content_code}/session_ids', item_id=f'{content_code}/session',
            data=json.dumps(payload).encode('ascii'), headers={
                'Content-Type': 'application/json',
                'Fc_use_device': 'null',
                'origin': 'https://kemomimirefle.net',
            },
            note='Getting session id', errnote='Unable to get session id',
        )['data']['session_id']

        return live_status, session_id
